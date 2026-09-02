from __future__ import annotations

import argparse
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from . import agent, normalize, search, storage
except ImportError:
    import agent
    import normalize
    import search
    import storage

STAGING_FILE = storage.ROOT / "data" / "review" / "specialty_staging.jsonl"


def needs_enrichment(record: dict, raw_by_id: dict, force: bool) -> bool:
    if record.get("food_specialty"):
        return False
    if not force and record.get("specialty_enrichment_attempted"):
        return False

    # A missing food_specialty from the deterministic (rule-based) path is often
    # correct and expected - e.g. OSM cuisine="moldovan" confidently gives a
    # cuisine_country with no dish-level token to report. Only venues that actually
    # went through the LLM path (i.e. normalize would send them to web search) have
    # a real evidence gap worth re-attempting.
    raw = raw_by_id.get(record["source_id"])
    if raw is None:
        return True  # no raw record to check against; err on the side of trying
    return normalize.normalize_record(raw["amenity"], raw["cuisine"]).needs_web_search


def merge_staged() -> None:
    """Applies every staged result (produced by run()) into classifications.jsonl /
    review_needed.jsonl, replacing each venue's old entry with the new one wherever it
    now belongs. Safe to call repeatedly - it always rebuilds from source_id, and
    clears the staging file only after a successful write."""
    staged = storage.load_jsonl(STAGING_FILE)
    if not staged:
        return

    staged_by_id = {r["source_id"]: r for r in staged}
    classifications = [r for r in storage.load_jsonl(storage.OUTPUT_FILE) if r["source_id"] not in staged_by_id]
    reviews = [r for r in storage.load_jsonl(storage.REVIEW_FILE) if r["source_id"] not in staged_by_id]

    for result in staged_by_id.values():
        (reviews if storage.is_low_confidence(result) else classifications).append(result)

    storage.write_jsonl(storage.OUTPUT_FILE, classifications)
    storage.write_jsonl(storage.REVIEW_FILE, reviews)
    STAGING_FILE.unlink()
    print(f"Merged {len(staged)} enriched result(s) into classifications/review files.")


def run(city: str = "Chisinau", limit: int | None = None, force: bool = False) -> None:
    merge_staged()  # apply any results left over from an interrupted previous run first

    classifications = storage.load_jsonl(storage.OUTPUT_FILE)
    reviews = storage.load_jsonl(storage.REVIEW_FILE)
    raw_by_id = {r["source_id"]: r for r in storage.load_raw_records()}

    targets = [r for r in classifications + reviews if needs_enrichment(r, raw_by_id, force)]
    if limit:
        targets = targets[:limit]

    print(f"Attempting to enrich food_specialty for {len(targets)} venue(s)...")

    gained, still_empty, failed = 0, 0, 0

    for n, record in enumerate(targets, 1):
        source_id = record["source_id"]
        raw = raw_by_id.get(source_id, {})
        name = record.get("name") or raw.get("name") or source_id
        print(f"[{n}/{len(targets)}] {name}")

        place = {
            "source_id": source_id,
            "name": name,
            "amenity": raw.get("amenity"),
            "cuisine": raw.get("cuisine"),
            "latitude": raw.get("latitude"),
            "longitude": raw.get("longitude"),
            "website": raw.get("website"),
            "phone": raw.get("phone"),
        }

        try:
            evidence = search.search_place(name, city=city)
            result = agent.classify_place(place, evidence)
        except Exception as exc:
            print(f"  failed (will retry next run): {exc}")
            failed += 1
            continue

        result["specialty_enrichment_attempted"] = True
        result["latitude"] = raw.get("latitude")
        result["longitude"] = raw.get("longitude")
        if result.get("food_specialty"):
            gained += 1
        else:
            still_empty += 1

        storage.append_jsonl(STAGING_FILE, result)

    print(f"\nDone. Gained food_specialty: {gained}. Still empty (no evidence found): {still_empty}. Failed: {failed}.")
    merge_staged()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retry food_specialty extraction for venues missing it.")
    parser.add_argument("--city", default="Chisinau")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true", help="Re-attempt even venues already marked as attempted.")
    parser.add_argument("--merge-only", action="store_true", help="Just merge any pending staged results, don't process new venues.")
    args = parser.parse_args()

    if args.merge_only:
        merge_staged()
    else:
        run(city=args.city, limit=args.limit, force=args.force)
