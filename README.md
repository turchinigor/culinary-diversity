# Culinary Classification Agent Starter

Purpose: enrich and normalize OSM food venues for the culinary-diversity project.

## Files

- `taxonomy.json` — allowed cuisine regions, cuisines, food specialties, concepts, normalization rules.
- `classification_schema.json` — exact JSON structure every classification must follow.
- `agent_prompt.txt` — classification instructions for LLM.
- `config.example.json` — starter project/search settings.
- `agent.py` — validation + prompt-building skeleton.
- `search.py` — simple web-search starter.
- `example_input.json` — sample OSM venue.
- `example_output.json` — sample valid result.
- `requirements.txt` — Python packages.

## Intended pipeline

OSM record
-> normalize useful existing cuisine tags
-> search web only when missing/ambiguous
-> collect evidence
-> LLM classification
-> validate against JSON schema + taxonomy
-> save one JSON object per line
-> send low-confidence/review cases to human review

## Output format

Use JSONL for bulk runs:

`data/classifications.jsonl`

One venue per line. Easier to retry, cache, resume, diff, and inspect than one giant JSON file.

## Important

`classification_schema.json` validates structure.

`taxonomy.json` validates meaning.

JSON Schema alone does not dynamically read allowed values from taxonomy, so `agent.py` performs second-stage taxonomy validation.

## Next implementation step

Wire a local model into `classify_place()`.

Recommended first experiment:
- Ollama for easiest local serving, or
- Hugging Face `transformers` pipeline.

Do not add autonomous browsing inside model. Keep:
1. search/retrieval
2. evidence extraction
3. classification

as separate steps.
