#!/usr/bin/env python3
"""Generate the published JSON/YAML files from the canonical CSV files.

Every output is rebuilt from scratch on each run, so running it twice produces
identical files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import yaml

from rtp_model import (
    REPO_ROOT,
    ClassCode,
    CsvFormatError,
    Dataset,
    DatasetError,
    Lineage,
    Verification,
    Year,
    format_timestamp,
)

SCHEMA_VERSION = 2
SOURCE_URL = "https://www.solotime.info/pax/"
_YEAR_FILE = re.compile(r"^[0-9]{4}\.(json|yaml)$")

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


def year_document(dataset: Dataset, year: Year) -> dict[str, JsonValue]:
    return {str(year): {str(e.code): float(e.index.value) for e in dataset.entries if e.year == year}}


def _link(year: Year, code: ClassCode, link: Lineage) -> dict[str, JsonValue]:
    return {"Year": year, "Class": str(code), "Relation": link.relation.value}


def combined_document(dataset: Dataset) -> dict[str, JsonValue]:
    predecessors: dict[ClassCode, list[JsonValue]] = defaultdict(list)
    successors: dict[ClassCode, list[JsonValue]] = defaultdict(list)
    for link in sorted(dataset.lineage, key=lambda l: (l.year, l.code, l.predecessor)):
        predecessors[link.code].append(_link(link.year, link.predecessor, link))
        successors[link.predecessor].append(_link(link.year, link.code, link))

    classes: dict[str, JsonValue] = {}
    for code in sorted({e.code for e in dataset.entries}):
        rtp: dict[str, JsonValue] = {}
        for entry in sorted((e for e in dataset.entries if e.code == code), key=lambda e: e.year):
            era = dataset.era_for(code, entry.year)
            rtp[str(entry.year)] = {
                "Index": float(entry.index.value),
                "Name": era.name,
                "SoloCategory": None if era.category is None else era.category.value,
                "ClassificationVerified": era.status is Verification.VERIFIED,
            }
        classes[str(code)] = {
            "RTP": rtp,
            "Predecessors": predecessors.get(code, []),
            "Successors": successors.get(code, []),
        }

    return {
        "SchemaVersion": SCHEMA_VERSION,
        "Source": SOURCE_URL,
        "Years": {
            str(record.year): {
                "Url": record.url,
                "PageLastUpdate": record.page_last_update.isoformat(),
                "RetrievedAt": format_timestamp(record.retrieved_at),
            }
            for record in sorted(dataset.sources, key=lambda r: r.year)
        },
        "SoloClasses": classes,
    }


def _json_text(document: JsonValue) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _yaml_text(document: JsonValue) -> str:
    return "---\n" + yaml.safe_dump(document, sort_keys=True, allow_unicode=True)


def build(dataset: Dataset) -> dict[Path, str]:
    """Return every output file (relative to the repo root) and its content."""
    files: dict[Path, str] = {}
    years = dataset.years()
    for year in years:
        document = year_document(dataset, year)
        files[Path("JSON") / f"{year}.json"] = _json_text(document)
        files[Path("YAML") / f"{year}.yaml"] = _yaml_text(document)
    latest = year_document(dataset, years[-1])
    files[Path("JSON") / "latest.json"] = _json_text(latest)
    files[Path("YAML") / "latest.yaml"] = _yaml_text(latest)
    combined = combined_document(dataset)
    files[Path("rtp.json")] = _json_text(combined)
    files[Path("rtp.yaml")] = _yaml_text(combined)
    return files


def write_outputs(root: Path, files: dict[Path, str]) -> None:
    for directory in {root / relative.parent for relative in files} | {root / "JSON", root / "YAML"}:
        if directory.is_symlink():
            raise RuntimeError(f"refusing to write through symlink: {directory}")
    for directory in ("JSON", "YAML"):
        for stale in (root / directory).glob("*"):
            if _YEAR_FILE.fullmatch(stale.name) and stale.relative_to(root) not in files:
                stale.unlink()
    for relative, content in files.items():
        path = root / relative
        if path.is_symlink():
            raise RuntimeError(f"refusing to write through symlink: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        dataset = Dataset.load(args.root / "CSV")
    except DatasetError as error:
        print("Canonical data is invalid:", file=sys.stderr)
        for problem in error.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    except CsvFormatError as error:
        print(f"Canonical data is invalid: {error}", file=sys.stderr)
        return 1
    write_outputs(args.root, build(dataset))
    return 0


if __name__ == "__main__":
    sys.exit(main())
