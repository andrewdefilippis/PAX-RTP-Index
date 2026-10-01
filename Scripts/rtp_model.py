"""Domain types and canonical CSV storage for PAX/RTP data.

The CSV files under CSV/ are the single source of truth. Every value read from
them is parsed into the types below; nothing downstream handles raw strings.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import NewType

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_DIR = REPO_ROOT / "CSV"

SOURCE_HOST = "www.solotime.info"
SOURCE_PATH_PREFIX = "/pax/"

FIRST_YEAR = 1995

Year = NewType("Year", int)

_YEAR = re.compile(r"^[0-9]{4}$")
_CODE = r"[A-Z0-9][A-Za-z0-9-]{0,7}"
_CLASS_CODE = re.compile(rf"^{_CODE}$")
_LABEL = re.compile(rf"^(?P<code>{_CODE})(?P<star>\*)?(?: ?\((?P<prev>{_CODE})\))?$")
_INDEX = re.compile(r"^(0\.[0-9]{3,4}|1\.0{3,4})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FREE_TEXT = re.compile(r"^[^<>`]+$")
_FORMULA_LEAD = ("=", "+", "-", "@")
_DISALLOWED_UNICODE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
_SOURCE_URL = re.compile(r"https://www\.solotime\.info/pax/(?:[A-Za-z0-9_-][A-Za-z0-9._-]*)?")
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse_year(raw: str) -> Year:
    if not _YEAR.fullmatch(raw) or int(raw) < FIRST_YEAR:
        raise ValueError(f"invalid year: {raw!r}")
    return Year(int(raw))


@dataclass(frozen=True, slots=True, order=True)
class ClassCode:
    value: str

    @classmethod
    def parse(cls, raw: str) -> ClassCode:
        if not _CLASS_CODE.fullmatch(raw):
            raise ValueError(f"invalid class code: {raw!r}")
        return cls(raw)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class RtpLabel:
    """A class label exactly as printed on the source page.

    Examples: "AS", "AS*" (footnote marker), "ST (STS)" and "AST(STR)" (a class
    code followed by a related former class code).
    """

    text: str
    code: ClassCode
    predecessor: ClassCode | None
    footnote: bool

    @classmethod
    def parse(cls, raw: str) -> RtpLabel:
        match = _LABEL.fullmatch(raw)
        if match is None:
            raise ValueError(f"invalid class label: {raw!r}")
        return cls(
            text=raw,
            code=ClassCode(match["code"]),
            predecessor=ClassCode(match["prev"]) if match["prev"] else None,
            footnote=match["star"] is not None,
        )

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True, slots=True)
class IndexValue:
    """An RTP index exactly as published, e.g. Decimal('0.820')."""

    value: Decimal

    @classmethod
    def parse(cls, raw: str) -> IndexValue:
        if not _INDEX.fullmatch(raw):
            raise ValueError(f"invalid index value: {raw!r}")
        return cls(Decimal(raw))

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class Sha256:
    hexdigest: str

    @classmethod
    def parse(cls, raw: str) -> Sha256:
        if not _SHA256.fullmatch(raw):
            raise ValueError(f"invalid sha256: {raw!r}")
        return cls(raw)

    def __str__(self) -> str:
        return self.hexdigest


class Category(StrEnum):
    """SCCA Solo category names as printed in the National Solo Rules."""

    STOCK = "Stock"
    STREET = "Street"
    STREET_R = "Street R"
    STREET_TOURING = "Street Touring"
    STREET_PREPARED = "Street Prepared"
    STREET_MODIFIED = "Street Modified"
    PREPARED = "Prepared"
    MODIFIED = "Modified"
    KART = "Kart"
    SOLO_SPEC_COUPE = "Solo Spec Coupe"
    CLASSIC_AMERICAN_MUSCLE = "Classic American Muscle"
    CLASSIC_AMERICAN_MUSCLE_XTREME_STREET = "Classic American Muscle / Xtreme Street"
    XTREME_STREET = "Xtreme Street"
    ELECTRIC_VEHICLE_EXPERIMENTAL = "Electric Vehicle Experimental"
    CLUB_SPEC = "Club Spec"
    HERITAGE_CLASSIC = "Heritage Classic"


class Verification(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class LineageRelation(StrEnum):
    RENAMED = "renamed"
    DERIVED = "derived"


@dataclass(frozen=True, slots=True)
class RtpEntry:
    year: Year
    code: ClassCode
    index: IndexValue
    label: RtpLabel

    def __post_init__(self) -> None:
        if self.label.code != self.code:
            raise ValueError(f"label {self.label.text!r} does not match class {self.code}")


@dataclass(frozen=True, slots=True)
class ClassEra:
    """A span of years with one SCCA name, category, and supporting citation.

    name and category are None only when no source could establish them, which
    requires status UNVERIFIED.
    """

    code: ClassCode
    first_year: Year
    last_year: Year | None
    name: str | None
    category: Category | None
    status: Verification
    source: str

    def __post_init__(self) -> None:
        if (self.name is None or self.category is None) and self.status is not Verification.UNVERIFIED:
            raise ValueError(f"{self.code}: unknown name/category requires status '{Verification.UNVERIFIED}'")

    def covers(self, year: Year) -> bool:
        return self.first_year <= year and (self.last_year is None or year <= self.last_year)


@dataclass(frozen=True, slots=True)
class Lineage:
    year: Year
    code: ClassCode
    predecessor: ClassCode
    relation: LineageRelation
    source: str


@dataclass(frozen=True, slots=True)
class SourceRecord:
    year: Year
    url: str
    page_last_update: date
    retrieved_at: datetime
    sha256: Sha256


class CsvFormatError(ValueError):
    def __init__(self, path: Path, line: int, message: str) -> None:
        super().__init__(f"{path}:{line}: {message}")


RTP_COLUMNS = ("year", "class", "index", "label")
CLASSES_COLUMNS = ("class", "first_year", "last_year", "name", "category", "status", "source")
LINEAGE_COLUMNS = ("year", "class", "predecessor", "relation", "source")
SOURCES_COLUMNS = ("year", "url", "page_last_update", "retrieved_at", "sha256")


def _free_text(raw: str, field: str) -> str:
    """Human-written text: non-empty, no control/markup characters, not a spreadsheet formula."""
    if not raw.strip():
        raise ValueError(f"{field} must not be empty")
    if (raw.startswith(_FORMULA_LEAD) or not _FREE_TEXT.fullmatch(raw)
            or any(unicodedata.category(ch) in _DISALLOWED_UNICODE_CATEGORIES for ch in raw)):
        raise ValueError(f"{field} contains disallowed characters: {raw!r}")
    return raw


def parse_source_url(raw: str) -> str:
    """A solotime.info PAX page URL: https, no userinfo/port/query/fragment, plain file name."""
    if not _SOURCE_URL.fullmatch(raw):
        raise ValueError(f"not a {SOURCE_HOST}{SOURCE_PATH_PREFIX} page URL: {raw!r}")
    return raw


def _parse_timestamp(raw: str) -> datetime:
    return datetime.strptime(raw, _TIMESTAMP_FORMAT).replace(tzinfo=UTC)


def format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)


def _read_rows(path: Path, columns: Sequence[str]) -> Iterable[tuple[int, dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != tuple(columns):
            raise CsvFormatError(path, 1, f"expected header {','.join(columns)}")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise CsvFormatError(path, reader.line_num, "wrong number of fields")
            yield reader.line_num, row


def _write_rows(path: Path, columns: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise RuntimeError(f"refusing to write through symlink: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)


def _parse_rows[T](path: Path, columns: Sequence[str], parse: Callable[[dict[str, str]], T]) -> list[T]:
    parsed: list[T] = []
    for line, row in _read_rows(path, columns):
        try:
            parsed.append(parse(row))
        except ValueError as error:
            raise CsvFormatError(path, line, str(error)) from error
    return parsed


def read_rtp(path: Path) -> list[RtpEntry]:
    return _parse_rows(path, RTP_COLUMNS, lambda row: RtpEntry(
        year=parse_year(row["year"]),
        code=ClassCode.parse(row["class"]),
        index=IndexValue.parse(row["index"]),
        label=RtpLabel.parse(row["label"]),
    ))


def write_rtp(path: Path, entries: Iterable[RtpEntry]) -> None:
    ordered = sorted(entries, key=lambda e: (e.year, e.code))
    _write_rows(path, RTP_COLUMNS, ((str(e.year), str(e.code), str(e.index), str(e.label)) for e in ordered))


def read_classes(path: Path) -> list[ClassEra]:
    return _parse_rows(path, CLASSES_COLUMNS, lambda row: ClassEra(
        code=ClassCode.parse(row["class"]),
        first_year=parse_year(row["first_year"]),
        last_year=parse_year(row["last_year"]) if row["last_year"] else None,
        name=_free_text(row["name"], "name") if row["name"] else None,
        category=Category(row["category"]) if row["category"] else None,
        status=Verification(row["status"]),
        source=_free_text(row["source"], "source"),
    ))


def write_classes(path: Path, eras: Iterable[ClassEra]) -> None:
    ordered = sorted(eras, key=lambda e: (e.code, e.first_year))
    _write_rows(path, CLASSES_COLUMNS, (
        (str(e.code), str(e.first_year), "" if e.last_year is None else str(e.last_year),
         e.name or "", "" if e.category is None else e.category.value, e.status.value, e.source)
        for e in ordered
    ))


def read_lineage(path: Path) -> list[Lineage]:
    return _parse_rows(path, LINEAGE_COLUMNS, lambda row: Lineage(
        year=parse_year(row["year"]),
        code=ClassCode.parse(row["class"]),
        predecessor=ClassCode.parse(row["predecessor"]),
        relation=LineageRelation(row["relation"]),
        source=_free_text(row["source"], "source"),
    ))


def write_lineage(path: Path, links: Iterable[Lineage]) -> None:
    ordered = sorted(links, key=lambda l: (l.year, l.code, l.predecessor))
    _write_rows(path, LINEAGE_COLUMNS, (
        (str(l.year), str(l.code), str(l.predecessor), l.relation.value, l.source) for l in ordered
    ))


def read_sources(path: Path) -> list[SourceRecord]:
    return _parse_rows(path, SOURCES_COLUMNS, lambda row: SourceRecord(
        year=parse_year(row["year"]),
        url=parse_source_url(row["url"]),
        page_last_update=date.fromisoformat(row["page_last_update"]),
        retrieved_at=_parse_timestamp(row["retrieved_at"]),
        sha256=Sha256.parse(row["sha256"]),
    ))


def write_sources(path: Path, records: Iterable[SourceRecord]) -> None:
    ordered = sorted(records, key=lambda r: r.year)
    _write_rows(path, SOURCES_COLUMNS, (
        (str(r.year), r.url, r.page_last_update.isoformat(), format_timestamp(r.retrieved_at), str(r.sha256))
        for r in ordered
    ))


class DatasetError(ValueError):
    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


@dataclass(frozen=True, slots=True)
class Dataset:
    entries: tuple[RtpEntry, ...]
    eras: tuple[ClassEra, ...]
    lineage: tuple[Lineage, ...]
    sources: tuple[SourceRecord, ...]

    @classmethod
    def load(cls, csv_dir: Path = CSV_DIR) -> Dataset:
        dataset = cls(
            entries=tuple(read_rtp(csv_dir / "rtp.csv")),
            eras=tuple(read_classes(csv_dir / "classes.csv")),
            lineage=tuple(read_lineage(csv_dir / "lineage.csv")),
            sources=tuple(read_sources(csv_dir / "sources.csv")),
        )
        problems = dataset.problems()
        if problems:
            raise DatasetError(problems)
        return dataset

    def years(self) -> list[Year]:
        return sorted({e.year for e in self.entries})

    def era_for(self, code: ClassCode, year: Year) -> ClassEra:
        matches = [era for era in self.eras if era.code == code and era.covers(year)]
        if len(matches) != 1:
            raise LookupError(f"{code} {year}: {len(matches)} matching eras")
        return matches[0]

    def problems(self) -> list[str]:
        problems: list[str] = []
        if not self.entries:
            problems.append("rtp.csv: no entries")

        for (year, code), count in Counter((e.year, e.code) for e in self.entries).items():
            if count > 1:
                problems.append(f"rtp.csv: {code} appears {count} times in {year}")

        eras_by_code: dict[ClassCode, list[ClassEra]] = defaultdict(list)
        for era in self.eras:
            if era.last_year is not None and era.last_year < era.first_year:
                problems.append(f"classes.csv: {era.code} era {era.first_year}-{era.last_year} ends before it starts")
            eras_by_code[era.code].append(era)
        for code, eras in eras_by_code.items():
            ordered = sorted(eras, key=lambda e: e.first_year)
            for earlier, later in zip(ordered, ordered[1:]):
                if earlier.last_year is None or earlier.last_year >= later.first_year:
                    problems.append(f"classes.csv: {code} eras starting {earlier.first_year} and {later.first_year} overlap")

        for entry in self.entries:
            covering = [era for era in eras_by_code.get(entry.code, []) if era.covers(entry.year)]
            if len(covering) != 1:
                problems.append(f"classes.csv: {entry.code} in {entry.year} is covered by {len(covering)} eras (expected 1)")

        years_by_code: dict[ClassCode, set[Year]] = defaultdict(set)
        for entry in self.entries:
            years_by_code[entry.code].add(entry.year)
        for link in self.lineage:
            if link.year not in years_by_code.get(link.code, set()):
                problems.append(f"lineage.csv: {link.code} has no rtp.csv entry in {link.year}")
            if not any(year < link.year for year in years_by_code.get(link.predecessor, set())):
                problems.append(f"lineage.csv: predecessor {link.predecessor} has no rtp.csv entry before {link.year}")
            if link.code == link.predecessor:
                problems.append(f"lineage.csv: {link.code} in {link.year} lists itself as predecessor")

        source_years = Counter(record.year for record in self.sources)
        for year, count in source_years.items():
            if count > 1:
                problems.append(f"sources.csv: {year} appears {count} times")
        for year in self.years():
            if year not in source_years:
                problems.append(f"sources.csv: no source record for {year}")

        return problems
