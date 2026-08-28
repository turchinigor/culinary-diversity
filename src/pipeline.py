from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from shapely import wkt

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from . import agent, normalize, search
except ImportError:
    import agent
    import normalize
    import search

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUTPUT_FILE = ROOT / "data" / "preprocessed" / "classifications.jsonl"
REVIEW_FILE = ROOT / "data" / "review" / "review_needed.jsonl"


def _clean(value: Any) -> Any:
    return None if pd.isna(value) else value


def load_raw_records() -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(RAW_DIR.glob("*.xlsx")):
        df = pd.read_excel(path)
        # to_excel(merge_cells=True) visually merges repeated consecutive values in a
        # MultiIndex column (element/id here); reading it back leaves those cells blank.
        # Data was written sorted by (element, id), so forward-fill recovers the true value.
        df["element"] = df["element"].ffill()
        for _, row in df.iterrows():
            source_id = f"{row['element']}/{row['id']}"
            if source_id in records:
                continue

            lat = lon = None
            geom_raw = _clean(row.get("geometry"))
            if geom_raw:
                try:
                    centroid = wkt.loads(geom_raw).centroid
                    lat, lon = centroid.y, centroid.x
                except Exception:
                    pass

            records[source_id] = {
                "source_id": source_id,
                "name": _clean(row.get("name")),
                "amenity": _clean(row.get("amenity")),
                "cuisine": _clean(row.get("cuisine")),
                "latitude": lat,
                "longitude": lon,
                "website": _clean(row.get("website")),
                "phone": _clean(row.get("phone")),
            }
    return list(records.values())


def load_processed_ids(*paths: Path) -> set[str]:
    seen: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                seen.add(json.loads(line)["source_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return seen


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(city: str = "Chisinau", limit: int | None = None, force: bool = False) -> None:
    records = load_raw_records()

    if not force:
        already_done = load_processed_ids(OUTPUT_FILE, REVIEW_FILE)
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
                append_jsonl(REVIEW_FILE, {**place, "error": str(exc), "stage": "search_or_classification"})
                continue
        else:
            result = normalize.to_classification(norm, place["source_id"], name)

        if result["include_recommended"] == "review" or result["classification_confidence"] == "low":
            append_jsonl(REVIEW_FILE, result)
        else:
            append_jsonl(OUTPUT_FILE, result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Normalize and classify OSM food venues.")
    parser.add_argument("--city", default="Chisinau", help="City name used in web-search queries.")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N unclassified venues.")
    parser.add_argument("--force", action="store_true", help="Reprocess venues already in output/review files.")
    args = parser.parse_args()
    run(city=args.city, limit=args.limit, force=args.force)
