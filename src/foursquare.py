from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from . import matching, storage
except ImportError:
    import matching
    import storage

FOURSQUARE_DIR = storage.ROOT / "data" / "foursquare"
MOLDOVA_PARQUET = FOURSQUARE_DIR / "moldova_places.parquet"
REPORT_FILE = FOURSQUARE_DIR / "foursquare_comparison.xlsx"

# Chisinau bounding box, same one used for the Overture pull.
CHISINAU_BBOX = (28.70, 46.93, 28.95, 47.10)  # (min_lon, min_lat, max_lon, max_lat)

# Foursquare's category hierarchy is "A > B > C"; match on the leaf segment.
LEAF_TO_TARGET = {
    "kebab restaurant": "kebab",
    "doner restaurant": "kebab",
    "pizzeria": "pizza",
    "burger joint": "burger",
    "sushi restaurant": "sushi",
}
FAST_FOOD_LEAF = "fast food restaurant"

MATCH_RADIUS_METERS = 100
NAME_SIMILARITY_THRESHOLD = 0.6


def _leaf(category_label: str) -> str:
    return category_label.rsplit(">", 1)[-1].strip().lower()


def load_foursquare_places(parquet_path: Path = MOLDOVA_PARQUET, bbox: tuple[float, float, float, float] = CHISINAU_BBOX) -> list[dict[str, Any]]:
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false;")
    rows = con.execute(
        f"""
        SELECT fsq_place_id, name, latitude, longitude, website, tel, instagram,
               date_closed, fsq_category_labels
        FROM '{parquet_path.as_posix()}'
        WHERE longitude BETWEEN {bbox[0]} AND {bbox[2]} AND latitude BETWEEN {bbox[1]} AND {bbox[3]}
          AND fsq_category_labels IS NOT NULL AND name IS NOT NULL
        """
    ).fetchall()

    places = []
    for fsq_id, name, lat, lon, website, tel, instagram, date_closed, labels in rows:
        leaves = {_leaf(label) for label in labels}
        targets = sorted({LEAF_TO_TARGET[leaf] for leaf in leaves if leaf in LEAF_TO_TARGET})
        is_fast_food = FAST_FOOD_LEAF in leaves
        if not targets and not is_fast_food:
            continue
        places.append({
            "fsq_place_id": fsq_id,
            "name": name,
            "latitude": lat,
            "longitude": lon,
            "website": website,
            "tel": tel,
            "instagram": instagram,
            "date_closed": date_closed,
            "categories": sorted(leaves & (set(LEAF_TO_TARGET) | {FAST_FOOD_LEAF})),
            "target_foods": targets,
            "is_fast_food": is_fast_food,
        })
    return places


def build_comparison_report(places: list[dict[str, Any]], existing_records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for place in places:
        match, score = matching.find_best_match(place, existing_records, MATCH_RADIUS_METERS, NAME_SIMILARITY_THRESHOLD)

        if match is None:
            status = "NEW_VENUE"
            existing_food_specialty = existing_concepts = ""
        else:
            existing_specialty = set(match.get("food_specialty") or [])
            missing_targets = set(place["target_foods"]) - existing_specialty
            existing_fast_food_flag = bool(
                set(match.get("establishment_concept") or []) & {"fast_food", "burger_shop", "kebab_shop", "snack_bar", "food_court_stall"}
            )
            if place["date_closed"]:
                status = "FLAG_POSSIBLY_CLOSED"
            elif missing_targets or (place["is_fast_food"] and not existing_fast_food_flag):
                status = "MATCH_ADDS_NEW_INFO"
            else:
                status = "MATCH_CONFIRMS_EXISTING"
            existing_food_specialty = "; ".join(sorted(existing_specialty))
            existing_concepts = "; ".join(sorted(match.get("establishment_concept") or []))

        rows.append({
            "status": status,
            "fsq_name": place["name"],
            "fsq_categories": "; ".join(place["categories"]),
            "target_foods": "; ".join(place["target_foods"]),
            "is_fast_food": place["is_fast_food"],
            "date_closed": place["date_closed"],
            "matched_source_id": match.get("source_id") if match else "",
            "matched_name": match.get("name") if match else "",
            "match_score": round(score, 2),
            "existing_food_specialty": existing_food_specialty,
            "existing_establishment_concept": existing_concepts,
            "fsq_website": place["website"],
            "fsq_tel": place["tel"],
            "fsq_instagram": place["instagram"],
            "latitude": place["latitude"],
            "longitude": place["longitude"],
        })

    df = pd.DataFrame(rows)
    status_order = {"FLAG_POSSIBLY_CLOSED": 0, "NEW_VENUE": 1, "MATCH_ADDS_NEW_INFO": 2, "MATCH_CONFIRMS_EXISTING": 3}
    df["_sort"] = df["status"].map(status_order)
    return df.sort_values("_sort").drop(columns="_sort")


def run(output: Path = REPORT_FILE) -> pd.DataFrame:
    places = load_foursquare_places()
    print(f"Loaded {len(places)} Foursquare places matching a target food or fast-food category.")

    classifications = storage.load_jsonl(storage.OUTPUT_FILE)
    reviews = storage.load_jsonl(storage.REVIEW_FILE)
    existing_records = classifications + reviews

    df = build_comparison_report(places, existing_records)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output, index=False)
    print(f"Wrote {len(df)} rows to {output}")
    print(df["status"].value_counts())
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare Foursquare Open Source Places against existing classifications (read-only report).")
    parser.add_argument("--output", type=Path, default=REPORT_FILE)
    args = parser.parse_args()
    run(args.output)
