from __future__ import annotations

import argparse
import json
import sys
from difflib import SequenceMatcher
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from . import storage
except ImportError:
    import storage

OVERTURE_FILE = storage.RAW_DIR / "overture_chisinau_places.geojson"

# Overture's place taxonomy already distinguishes these as controlled categories -
# no LLM or web search needed to get this signal.
CATEGORY_TO_TARGET = {
    "doner_kebab": "kebab",
    "kebab_restaurant": "kebab",
    "shawarma_restaurant": "kebab",
    "pizza_restaurant": "pizza",
    "burger_restaurant": "burger",
    "hamburger_restaurant": "burger",
    "sushi_restaurant": "sushi",
}

TARGET_TO_CONCEPT = {
    "kebab": "kebab_shop",
    "pizza": "pizzeria",
    "burger": "burger_shop",
    "sushi": "sushi_restaurant",
}

TARGET_TO_SCOPE = {
    "kebab": "limited_meal",
    "pizza": "full_meal",
    "burger": "limited_meal",
    "sushi": "full_meal",
}

MATCH_RADIUS_METERS = 100
NAME_SIMILARITY_THRESHOLD = 0.6
CONFIDENT_THRESHOLD = 0.5


def load_overture_places(path: Path = OVERTURE_FILE) -> list[dict[str, Any]]:
    """Loads only Overture places whose category matches one of the 4 target foods."""
    data = json.loads(path.read_text(encoding="utf-8"))
    places = []
    for feature in data["features"]:
        props = feature["properties"]
        name = (props.get("names") or {}).get("primary")
        if not name:
            continue

        cats = props.get("categories") or {}
        all_cats = {cats["primary"]} if cats.get("primary") else set()
        all_cats.update(cats.get("alternate") or [])
        targets = sorted({CATEGORY_TO_TARGET[c] for c in all_cats if c in CATEGORY_TO_TARGET})
        if not targets:
            continue

        lon, lat = feature["geometry"]["coordinates"]
        websites = props.get("websites") or []
        places.append({
            "overture_id": feature["id"],
            "name": name,
            "latitude": lat,
            "longitude": lon,
            "target_foods": targets,
            "matched_categories": sorted(all_cats & set(CATEGORY_TO_TARGET)),
            "confidence": props.get("confidence"),
            "website": websites[0] if websites else None,
        })
    return places


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def find_best_match(overture_place: dict[str, Any], existing_records: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    best, best_score = None, 0.0
    for record in existing_records:
        lat, lon = record.get("latitude"), record.get("longitude")
        if lat is None or lon is None or not record.get("name"):
            continue
        if _haversine_meters(overture_place["latitude"], overture_place["longitude"], lat, lon) > MATCH_RADIUS_METERS:
            continue
        score = _name_similarity(overture_place["name"], record["name"])
        if score > best_score:
            best, best_score = record, score
    if best_score >= NAME_SIMILARITY_THRESHOLD:
        return best, best_score
    return None, best_score


def apply_match_to_existing(record: dict[str, Any], overture_place: dict[str, Any], score: float) -> bool:
    """Adds any newly-confirmed target foods to an existing record. Returns True if
    the record actually changed."""
    new_targets = [t for t in overture_place["target_foods"] if t not in (record.get("food_specialty") or [])]
    if not new_targets:
        return False

    record["food_specialty"] = sorted(set(record.get("food_specialty") or []) | set(new_targets))
    new_concepts = {TARGET_TO_CONCEPT[t] for t in new_targets}
    record["establishment_concept"] = sorted(set(record.get("establishment_concept") or []) | new_concepts)

    note = f"Overture Maps category match: {', '.join(overture_place['matched_categories'])} (confidence {overture_place['confidence']:.2f}, name match {score:.2f})"
    record.setdefault("classification_sources", []).append({"source_type": "other", "url": overture_place["website"], "note": note})
    record["evidence"] = (record.get("evidence") or "").rstrip() + " " + note

    if overture_place["confidence"] >= CONFIDENT_THRESHOLD and record.get("classification_confidence") == "low":
        record["classification_confidence"] = "medium"
        record["include_recommended"] = "yes"
        if record.get("food_service_scope") in (None, "unknown"):
            record["food_service_scope"] = TARGET_TO_SCOPE[new_targets[0]]

    return True


def build_new_record(overture_place: dict[str, Any]) -> dict[str, Any]:
    confident = overture_place["confidence"] is not None and overture_place["confidence"] >= CONFIDENT_THRESHOLD
    concepts = sorted({TARGET_TO_CONCEPT[t] for t in overture_place["target_foods"]})
    note = f"Overture Maps category: {', '.join(overture_place['matched_categories'])} (confidence {overture_place['confidence']:.2f})"

    return {
        "source_id": f"overture/{overture_place['overture_id']}",
        "name": overture_place["name"],
        "include_recommended": "yes" if confident else "review",
        "food_service_scope": TARGET_TO_SCOPE[overture_place["target_foods"][0]],
        "establishment_concept": concepts,
        "cuisine_region": [],
        "cuisine_country": [],
        "food_specialty": overture_place["target_foods"],
        "classification_confidence": "medium" if confident else "low",
        "classification_sources": [{"source_type": "other", "url": overture_place["website"], "note": note}],
        "evidence": note + " Not present in the original OSM-derived venue list.",
        "unmapped_findings": [],
        "latitude": overture_place["latitude"],
        "longitude": overture_place["longitude"],
    }


def run(overture_path: Path = OVERTURE_FILE, limit: int | None = None) -> None:
    overture_places = load_overture_places(overture_path)
    if limit:
        overture_places = overture_places[:limit]
    print(f"Loaded {len(overture_places)} Overture places matching a target food category.")

    classifications = storage.load_jsonl(storage.OUTPUT_FILE)
    reviews = storage.load_jsonl(storage.REVIEW_FILE)
    all_existing = classifications + reviews

    updated, added, unchanged = 0, 0, 0
    new_records: list[dict[str, Any]] = []

    for place in overture_places:
        match, score = find_best_match(place, all_existing)
        if match is not None:
            if apply_match_to_existing(match, place, score):
                updated += 1
            else:
                unchanged += 1
        else:
            new_records.append(build_new_record(place))
            added += 1

    for record in new_records:
        destination = reviews if storage.is_low_confidence(record) else classifications
        destination.append(record)

    storage.write_jsonl(storage.OUTPUT_FILE, classifications)
    storage.write_jsonl(storage.REVIEW_FILE, reviews)

    print(f"Updated existing venues: {updated}")
    print(f"Already had the target food (no change): {unchanged}")
    print(f"New venues added: {added}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cross-reference Overture Maps places against existing classifications.")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    run(limit=args.limit)
