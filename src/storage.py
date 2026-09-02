from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from shapely import wkt

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUTPUT_FILE = ROOT / "data" / "preprocessed" / "classifications.jsonl"
REVIEW_FILE = ROOT / "data" / "review" / "review_needed.jsonl"
ERROR_FILE = ROOT / "data" / "review" / "errors.jsonl"


def is_low_confidence(result: dict[str, Any]) -> bool:
    return result["include_recommended"] == "review" or result["classification_confidence"] == "low"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # tolerate a truncated last line from an interrupted write
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_processed_ids(*paths: Path) -> set[str]:
    return {record["source_id"] for path in paths for record in load_jsonl(path)}


def _clean(value: Any) -> Any:
    return None if pd.isna(value) else value


def load_raw_records() -> list[dict[str, Any]]:
    """Loads every scraped OSM venue from data/raw/*.xlsx, deduplicated by (element, id)."""
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
