from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import validate

try:
    from . import llm_client
except ImportError:
    import llm_client

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY = json.loads((ROOT / "taxonomy" / "taxonomy.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "taxonomy" / "classification_schema.json").read_text(encoding="utf-8"))
PROMPT = (ROOT / "prompts" / "agent_prompt.txt").read_text(encoding="utf-8")


def validate_taxonomy_values(result: dict[str, Any]) -> None:
    allowed_regions = set(TAXONOMY["cuisine_regions"])
    allowed_countries = set(TAXONOMY["cuisine_countries"])
    allowed_specialties = set(TAXONOMY["food_specialties"])
    allowed_concepts = set(TAXONOMY["establishment_concepts"])

    checks = {
        "cuisine_region": allowed_regions,
        "cuisine_country": allowed_countries,
        "food_specialty": allowed_specialties,
        "establishment_concept": allowed_concepts,
    }

    for field, allowed in checks.items():
        invalid = [value for value in result[field] if value not in allowed]
        if invalid:
            raise ValueError(f"Invalid taxonomy value(s) in {field}: {invalid}")


def sanitize_taxonomy_values(result: dict[str, Any]) -> dict[str, Any]:
    """Moves any off-taxonomy value the LLM put in a controlled field into
    unmapped_findings instead, per the project's own unmapped_findings design -
    the model reliably finds real evidence but not as reliably remembers to route
    values outside the controlled vocabulary there itself."""
    checks = {
        "cuisine_region": set(TAXONOMY["cuisine_regions"]),
        "cuisine_country": set(TAXONOMY["cuisine_countries"]),
        "food_specialty": set(TAXONOMY["food_specialties"]),
        "establishment_concept": set(TAXONOMY["establishment_concepts"]),
    }

    for field, allowed in checks.items():
        kept, moved = [], []
        for value in result.get(field, []):
            (kept if value in allowed else moved).append(value)
        result[field] = kept
        for value in moved:
            result["unmapped_findings"].append(
                {"type": field, "value": value, "note": "auto-moved: not in controlled taxonomy"}
            )
    return result


def validate_result(result: dict[str, Any]) -> None:
    validate(instance=result, schema=SCHEMA)
    validate_taxonomy_values(result)


def build_llm_input(place: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    payload = {
        "venue": place,
        "web_evidence": evidence,
        "output_schema": SCHEMA,
        "taxonomy": {
            "cuisine_regions": TAXONOMY["cuisine_regions"],
            "cuisine_countries": TAXONOMY["cuisine_countries"],
            "establishment_concepts": TAXONOMY["establishment_concepts"],
            "food_specialties": TAXONOMY["food_specialties"],
            "guardrails": TAXONOMY["guardrails"],
        },
    }
    return PROMPT + "\n\nINPUT:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object found in model output: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def classify_place(place: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep web search separate from classification, for easier debugging."""
    prompt = build_llm_input(place, evidence)
    raw_output = llm_client.complete(prompt)
    result = _extract_json_object(raw_output)
    validate(instance=result, schema=SCHEMA)
    sanitize_taxonomy_values(result)
    validate_result(result)
    return result


if __name__ == "__main__":
    example_place = json.loads((ROOT / "examples" / "example_input.json").read_text(encoding="utf-8"))
    print(build_llm_input(example_place, evidence=[]))
