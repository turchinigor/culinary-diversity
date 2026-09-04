from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from . import storage
except ImportError:
    import storage

CLASSIFICATIONS_COLUMNS = [
    "source_id",
    "name",
    "include_recommended",
    "classification_confidence",
    "food_service_scope",
    "establishment_concept",
    "cuisine_region",
    "cuisine_country",
    "food_specialty",
    "evidence",
    "sources_summary",
    "unmapped_summary",
    "latitude",
    "longitude",
]

REVIEW_COLUMNS = [
    "source_id",
    "name",
    "amenity",
    "cuisine",
    "include_recommended",
    "classification_confidence",
    "food_service_scope",
    "establishment_concept",
    "cuisine_region",
    "cuisine_country",
    "food_specialty",
    "evidence",
    "sources_summary",
    "unmapped_summary",
    "website",
    "phone",
    "latitude",
    "longitude",
    "human_decision",
    "human_notes",
]

SHEETS = {
    "classifications": (storage.OUTPUT_FILE, CLASSIFICATIONS_COLUMNS),
    "review": (storage.REVIEW_FILE, REVIEW_COLUMNS),
}

SPECIALTY_COLUMNS = [
    "source_id",
    "name",
    "origin",
    "food_specialty",
    "cuisine_country",
    "cuisine_region",
    "establishment_concept",
    "food_service_scope",
    "include_recommended",
    "classification_confidence",
    "latitude",
    "longitude",
]


def _join(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return "" if value is None else str(value)


def _summarize_sources(sources: Any) -> str:
    if not isinstance(sources, list):
        return ""
    parts = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        bit = s.get("source_type", "?")
        if s.get("url"):
            bit += f" ({s['url']})"
        parts.append(bit)
    return "; ".join(parts)


def _summarize_unmapped(findings: Any) -> str:
    if not isinstance(findings, list):
        return ""
    return "; ".join(f"{f.get('type')}={f.get('value')}" for f in findings if isinstance(f, dict))


def build_sheet(records: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    rows = []
    for record in records:
        row = dict(record)
        row["establishment_concept"] = _join(record.get("establishment_concept"))
        row["cuisine_region"] = _join(record.get("cuisine_region"))
        row["cuisine_country"] = _join(record.get("cuisine_country"))
        row["food_specialty"] = _join(record.get("food_specialty"))
        row["sources_summary"] = _summarize_sources(record.get("classification_sources"))
        row["unmapped_summary"] = _summarize_unmapped(record.get("unmapped_findings"))
        if "human_decision" in columns:
            row.setdefault("human_decision", "")
            row.setdefault("human_notes", "")
        rows.append(row)

    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns]


def export(which: str, output: Path | None = None) -> Path:
    if which == "specialty":
        classifications = [{**r, "origin": "classifications"} for r in storage.load_jsonl(storage.OUTPUT_FILE)]
        reviews = [{**r, "origin": "review"} for r in storage.load_jsonl(storage.REVIEW_FILE)]
        with_specialty = [r for r in classifications + reviews if r.get("food_specialty")]
        df = build_sheet(with_specialty, SPECIALTY_COLUMNS)
        output = output or storage.OUTPUT_FILE.parent / "venues_with_specialty.xlsx"
        df.to_excel(output, index=False)
        print(f"Wrote {len(df)} rows to {output}")
        print(df["origin"].value_counts())
        return output

    source_file, columns = SHEETS[which]
    df = build_sheet(storage.load_jsonl(source_file), columns)
    output = output or source_file.with_suffix(".xlsx")
    df.to_excel(output, index=False)
    print(f"Wrote {len(df)} rows to {output}")
    print(df["classification_confidence"].value_counts())
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export classification data to a spreadsheet.")
    parser.add_argument("--which", choices=[*SHEETS.keys(), "specialty"], required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    export(args.which, args.output)
