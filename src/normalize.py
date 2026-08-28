from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY = json.loads((ROOT / "taxonomy" / "taxonomy.json").read_text(encoding="utf-8"))

OSM_TOKEN_MAP: dict[str, dict[str, Any]] = TAXONOMY["osm_token_map"]
CUISINE_COUNTRY_REGIONS: dict[str, str] = TAXONOMY["cuisine_countries"]

_ESTABLISHMENT_CONCEPTS = {v.lower(): v for v in TAXONOMY["establishment_concepts"]}
_FOOD_SPECIALTIES = {v.lower(): v for v in TAXONOMY["food_specialties"]}
_CUISINE_COUNTRIES = {v.lower(): v for v in CUISINE_COUNTRY_REGIONS}
_CUISINE_REGIONS = {v.lower(): v for v in TAXONOMY["cuisine_regions"]}

# Specialties that alone are enough to call a venue a "full meal" establishment.
HEAVY_SPECIALTIES = {
    "grill", "steak", "burger", "pizza", "kebab", "shawarma", "seafood", "ramen",
    "pasta", "curry", "rice_dishes", "barbecue", "chicken", "fish", "tacos",
    "burrito", "dumplings",
}
DESSERT_SPECIALTIES = {"dessert", "ice_cream", "cake", "donut", "pastry"}

FOOD_SERVICE_AMENITIES = {"restaurant", "fast_food"}
DRINK_FIRST_AMENITIES = {"bar", "pub", "cafe"}
DRINK_FIRST_CONCEPT = {"bar": "bar_with_food", "pub": "pub_with_food", "cafe": "cafe_with_food"}

SPECIALTY_TO_CONCEPT = {
    "pizza": "pizzeria",
    "sushi": "sushi_restaurant",
    "kebab": "kebab_shop",
    "shawarma": "kebab_shop",
    "burger": "burger_shop",
    "ramen": "ramen_shop",
    "steak": "steakhouse",
    "seafood": "seafood_restaurant",
    "grill": "grill_house",
}


@dataclass
class NormalizationResult:
    cuisine_country: set[str] = field(default_factory=set)
    cuisine_region: set[str] = field(default_factory=set)
    food_specialty: set[str] = field(default_factory=set)
    establishment_concept: set[str] = field(default_factory=set)
    beverage: set[str] = field(default_factory=set)
    unmapped_tokens: set[str] = field(default_factory=set)

    include_recommended: str | None = None
    food_service_scope: str | None = None
    needs_web_search: bool = True
    confidence: str = "medium"
    reason: str = ""


def split_osm_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return []
    return [token.strip().lower() for token in text.split(";") if token.strip()]


def _classify_token(token: str, result: NormalizationResult) -> None:
    entry = OSM_TOKEN_MAP.get(token)
    if entry is not None:
        kind = entry["kind"]
        if kind == "cuisine_country":
            result.cuisine_country.add(entry["value"])
            result.cuisine_region.add(entry["region"])
        elif kind == "cuisine_region":
            result.cuisine_region.add(entry["value"])
        elif kind == "food_specialty":
            result.food_specialty.add(entry["specialty"])
        elif kind == "establishment_concept":
            result.establishment_concept.add(entry["value"])
        elif kind == "beverage":
            result.beverage.add(entry["value"])
        # "ambiguous_geography" and "meal_period" tokens carry no classification weight
        return

    if token in _ESTABLISHMENT_CONCEPTS:
        result.establishment_concept.add(_ESTABLISHMENT_CONCEPTS[token])
    elif token in _FOOD_SPECIALTIES:
        result.food_specialty.add(_FOOD_SPECIALTIES[token])
    elif token in _CUISINE_COUNTRIES:
        canonical = _CUISINE_COUNTRIES[token]
        result.cuisine_country.add(canonical)
        result.cuisine_region.add(CUISINE_COUNTRY_REGIONS[canonical])
    elif token in _CUISINE_REGIONS:
        result.cuisine_region.add(_CUISINE_REGIONS[token])
    else:
        result.unmapped_tokens.add(token)


def normalize_record(amenity: str | None, raw_cuisine: Any) -> NormalizationResult:
    result = NormalizationResult()
    tokens = split_osm_list(raw_cuisine)
    for token in tokens:
        _classify_token(token, result)

    for specialty, concept in SPECIALTY_TO_CONCEPT.items():
        if specialty in result.food_specialty:
            result.establishment_concept.add(concept)

    savory_specialty = result.food_specialty - DESSERT_SPECIALTIES
    has_food_signal = bool(savory_specialty or result.cuisine_country or result.cuisine_region)
    dessert_only_signal = bool(result.food_specialty & DESSERT_SPECIALTIES) and not has_food_signal
    # Explicit tokens present, but none of them signal real savory food.
    beverage_or_dessert_only = bool(tokens) and not has_food_signal and not result.unmapped_tokens

    if amenity in FOOD_SERVICE_AMENITIES:
        result.establishment_concept.add(amenity)
        if not tokens or result.unmapped_tokens:
            result.needs_web_search = True
            result.reason = "cuisine missing or contains unrecognized tokens"
        elif has_food_signal:
            result.include_recommended = "yes"
            result.food_service_scope = "full_meal" if amenity == "restaurant" else "limited_meal"
            if savory_specialty & HEAVY_SPECIALTIES:
                result.food_service_scope = "full_meal"
            result.needs_web_search = False
            result.confidence = "medium"
            result.reason = "OSM cuisine tokens gave a clear food classification"
        else:
            result.needs_web_search = True
            result.reason = "cuisine tokens present but give no concrete savory-food evidence"

    elif amenity in DRINK_FIRST_AMENITIES:
        if not tokens:
            # e.g. a pub with no OSM cuisine tag can still run a full food menu
            # (see examples/example_input.json "Draft Arena") - missing cuisine
            # on a drink-first venue is not itself evidence of drinks-only.
            result.needs_web_search = True
            result.reason = "no cuisine tag on a drink-first amenity; food offer unknown"
        elif beverage_or_dessert_only:
            result.include_recommended = "no"
            result.food_service_scope = "dessert_only" if dessert_only_signal else "drinks_only"
            result.needs_web_search = False
            result.confidence = "high"
            result.reason = "explicit beverage/dessert-only tokens, no savory food evidence"
        elif result.unmapped_tokens:
            result.needs_web_search = True
            result.reason = "unrecognized cuisine tokens on a drink-first amenity"
        elif has_food_signal:
            result.include_recommended = "yes"
            result.establishment_concept.add(DRINK_FIRST_CONCEPT[amenity])
            if savory_specialty & HEAVY_SPECIALTIES or result.cuisine_country:
                result.food_service_scope = "full_meal"
            else:
                result.food_service_scope = "limited_meal"
            result.needs_web_search = False
            result.confidence = "medium"
            result.reason = "OSM cuisine tokens show a real food offer on a drink-first amenity"
        else:
            result.needs_web_search = True
            result.reason = "only ambiguous geography tokens, no concrete food evidence"
    else:
        result.needs_web_search = True
        result.reason = f"unhandled amenity: {amenity!r}"

    return result


def to_classification(result: NormalizationResult, source_id: str, name: str) -> dict[str, Any]:
    """Builds a schema-valid classification straight from a deterministic normalization,
    for the cases where OSM tags already gave a confident answer (no LLM call needed)."""
    return {
        "source_id": source_id,
        "name": name,
        "include_recommended": result.include_recommended or "review",
        "food_service_scope": result.food_service_scope or "unknown",
        "establishment_concept": sorted(result.establishment_concept),
        "cuisine_region": sorted(result.cuisine_region),
        "cuisine_country": sorted(result.cuisine_country),
        "food_specialty": sorted(result.food_specialty),
        "classification_confidence": result.confidence,
        "classification_sources": [{"source_type": "osm", "url": None, "note": result.reason}],
        "evidence": result.reason,
        "unmapped_findings": [],
    }
