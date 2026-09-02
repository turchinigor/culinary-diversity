from __future__ import annotations

import argparse
import json
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


def prune_stale_errors(done_ids: set[str]) -> None:
    """Removes errors.jsonl entries for venues that have since succeeded (in done_ids),
    and collapses repeated failures of the same venue down to the latest one - otherwise
    a resolved error lingers forever, or the same venue piles up one line per failed retry."""
    lines = storage.ERROR_FILE.read_text(encoding="utf-8").splitlines() if storage.ERROR_FILE.exists() else []
    lines = [line for line in lines if line.strip()]
    latest_by_id: dict[str, str] = {}
    for line in lines:
        source_id = json.loads(line)["source_id"]
        if source_id not in done_ids:
            latest_by_id[source_id] = line  # later lines overwrite earlier ones for the same id
    kept = list(latest_by_id.values())
    if kept != lines:
        storage.ERROR_FILE.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")


def run(city: str = "Chisinau", limit: int | None = None, force: bool = False) -> None:
    records = storage.load_raw_records()

    if not force:
        already_done = storage.load_processed_ids(storage.OUTPUT_FILE, storage.REVIEW_FILE)
        prune_stale_errors(already_done)
        records = [r for r in records if r["source_id"] not in already_done]

    if limit:
        records = records[:limit]

    print(f"Processing {len(records)} venue(s)...")

    for i, place in enumerate(records, 1):
        name = place["name"] or place["source_id"]
        print(f"[{i}/{len(records)}] {name} ({place['amenity']})")

        norm = normalize.normalize_record(place["amenity"], place["cuisine"])

        if norm.needs_web_search:
            try:
                evidence = search.search_place(name, city=city)
                result = agent.classify_place({**place, "name": name}, evidence)
            except Exception as exc:
                # Not counted as "done" by load_processed_ids, so a rerun retries it -
                # this is usually a transient failure (network blip, API quota), not a
                # real judgment call about the venue.
                storage.append_jsonl(storage.ERROR_FILE, {**place, "error": str(exc), "stage": "search_or_classification"})
                continue
        else:
            result = normalize.to_classification(norm, place["source_id"], name)

        result["latitude"] = place["latitude"]
        result["longitude"] = place["longitude"]

        destination = storage.REVIEW_FILE if storage.is_low_confidence(result) else storage.OUTPUT_FILE
        storage.append_jsonl(destination, result)

    if not force:
        # Re-prune with this run's own new results, so a venue that just succeeded
        # doesn't sit stale in errors.jsonl until the next unrelated run.
        prune_stale_errors(storage.load_processed_ids(storage.OUTPUT_FILE, storage.REVIEW_FILE))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Normalize and classify OSM food venues.")
    parser.add_argument("--city", default="Chisinau", help="City name used in web-search queries.")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N unclassified venues.")
    parser.add_argument("--force", action="store_true", help="Reprocess venues already in output/review files.")
    args = parser.parse_args()
    run(city=args.city, limit=args.limit, force=args.force)
