# Changelog

## 2.0.0

The data is now maintained in `CSV/`, and every JSON/YAML file is generated from it.

### Breaking changes

* `rtp.json` / `rtp.yaml` have a new shape ([schema](Schema/rtp.schema.json)), identified by `"SchemaVersion": 2`:
  * `SoloClasses.<class>.RTP` is now an object keyed by year (`{"2025": {"Index": 0.834, "Name": ..., "SoloCategory": ...}}`) instead of a list of single-key objects. A year can no longer appear twice.
  * `SoloCategory` moved inside each year, because SCCA categories change over time. Categories now follow the names in that year's SCCA National Solo Rules where a source exists; `ClassificationVerified` says whether it does.
  * Added `Name`, `ClassificationVerified`, `Predecessors`, `Successors`, and top-level `Years` (source URL, page "Last update" date, retrieval time).
  * `Name` and `SoloCategory` are `null` for the few early classes no source names (T-1/T-2/T-3 in 1998, FJr, SFJr).
* 2025 and 2026 class keys in `JSON/<year>.json` / `YAML/<year>.yaml` changed from `AST(STR)`, `BST(STU)`, `DST(STX)`, `EST(STS)`, `GST(STH)` to `AST`, `BST`, `DST`, `EST`, `GST`. The parenthesized former class is now recorded as lineage.
* The top-level year key in `YAML/<year>.yaml` is now a string (`'2025':`) instead of an integer, matching the JSON files.

### Data corrections

* 2024: updated to solotime.info's revision of December 20, 2023. `XS` and `SSR` removed, `XU` (0.869) added, `EVX` 0.830 → 0.834, `XA` 0.842 → 0.844.
* 2026: updated to solotime.info's revision of March 20, 2026 (the January 4 values predated it). `CAM-C` 0.827 → 0.828, `GS` 0.793 → 0.809, `SS` 0.837 → 0.840, `XU` 0.869 → 0.872.

### Removals

* `Scripts/rtp_form_generator.py` (unfinished) and the `jsonmerge` / `json2table` dependencies.
* `requirements.txt`. Dependencies are now managed with [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`).

### Additions

* `JSON/latest.json`, `YAML/latest.yaml`.
* `CSV/` canonical data, `Schema/` JSON Schemas.
* Weekly automated check for new or revised indices.
