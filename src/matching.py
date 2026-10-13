from __future__ import annotations

from difflib import SequenceMatcher
from math import atan2, cos, radians, sin, sqrt
from typing import Any

DEFAULT_MATCH_RADIUS_METERS = 100
DEFAULT_NAME_SIMILARITY_THRESHOLD = 0.6


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def find_best_match(
    candidate: dict[str, Any],
    existing_records: list[dict[str, Any]],
    radius_meters: float = DEFAULT_MATCH_RADIUS_METERS,
    similarity_threshold: float = DEFAULT_NAME_SIMILARITY_THRESHOLD,
) -> tuple[dict[str, Any] | None, float]:
    """Finds the existing record closest in name to `candidate` among those within
    `radius_meters`. `candidate` and each record need "name", "latitude", "longitude"."""
    best, best_score = None, 0.0
    for record in existing_records:
        lat, lon = record.get("latitude"), record.get("longitude")
        if lat is None or lon is None or not record.get("name"):
            continue
        if haversine_meters(candidate["latitude"], candidate["longitude"], lat, lon) > radius_meters:
            continue
        score = name_similarity(candidate["name"], record["name"])
        if score > best_score:
            best, best_score = record, score
    if best_score >= similarity_threshold:
        return best, best_score
    return None, best_score
