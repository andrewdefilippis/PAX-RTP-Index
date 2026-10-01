#!/usr/bin/env python3
"""Fetch PAX/RTP pages from solotime.info and update the canonical CSV files.

Only CSV/rtp.csv and CSV/sources.csv are written. JSON/YAML outputs are produced
by rtp_files_generator.py.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from bs4 import BeautifulSoup

from rtp_model import (
    CSV_DIR,
    FIRST_YEAR,
    SOURCE_HOST,
    ClassCode,
    IndexValue,
    RtpEntry,
    RtpLabel,
    Sha256,
    SourceRecord,
    Year,
    parse_source_url,
    read_classes,
    read_lineage,
    read_rtp,
    read_sources,
    write_rtp,
    write_sources,
)

BASE_URL = f"https://{SOURCE_HOST}/pax/"
ARCHIVE_URL = BASE_URL + "rtp{year}.html"
USER_AGENT = "PAX-RTP-Index/2 (+https://github.com/andrewdefilippis/PAX-RTP-Index)"
CRAWL_DELAY_SECONDS = 10.0
TIMEOUT_SECONDS = 30.0
DEADLINE_SECONDS = 60.0
READ_CHUNK_BYTES = 16_384
MAX_RETRIES = 2
MAX_PAGE_BYTES = 1_000_000
MIN_CLASSES = 15
MAX_CLASSES = 80

_HEADER = re.compile(r"^(?P<year>[0-9]{4})\s+(?:PAX/)?RTP Index\b")
_LAST_UPDATE = re.compile(r"Last\s+update\s+(?P<month>[A-Z][a-z]+)\.?\s+(?P<day>[0-9]{1,2}),?\s+(?P<year>[0-9]{4})")
_VALUE = re.compile(r"^(?P<num>[01]?\.[0-9]{3,4})\.?$")
_MONTHS = {name: number for number, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"), start=1)}


class PageParseError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ParsedEntry:
    label: RtpLabel
    index: IndexValue


@dataclass(frozen=True, slots=True)
class ParsedPage:
    year: Year
    page_last_update: date
    entries: tuple[ParsedEntry, ...]


def parse_label(text: str) -> RtpLabel | None:
    try:
        return RtpLabel.parse(text)
    except ValueError:
        return None


def parse_value(text: str) -> IndexValue | None:
    match = _VALUE.fullmatch(text)
    if match is None:
        return None
    number = match["num"]
    try:
        return IndexValue.parse("0" + number if number.startswith(".") else number)
    except ValueError as error:
        raise PageParseError(str(error)) from error


def _parse_year(soup: BeautifulSoup) -> Year:
    years = set()
    for header in soup.find_all("h1"):
        match = _HEADER.match(" ".join(header.get_text().split()))
        if match:
            years.add(Year(int(match["year"])))
    if len(years) != 1:
        raise PageParseError(f"expected exactly one '<year> PAX/RTP Index' heading, found {sorted(years)}")
    year = years.pop()
    latest = datetime.now(UTC).year + 1
    if not FIRST_YEAR <= year <= latest:
        raise PageParseError(f"page year {year} is outside {FIRST_YEAR}-{latest}")
    return year


def _parse_last_update(soup: BeautifulSoup) -> date:
    matches = list(_LAST_UPDATE.finditer(" ".join(soup.get_text().split())))
    if len(matches) != 1:
        raise PageParseError(f"expected exactly one 'Last update' date, found {len(matches)}")
    match = matches[0]
    if match["month"] not in _MONTHS:
        raise PageParseError(f"unknown month in 'Last update': {match['month']!r}")
    try:
        return date(int(match["year"]), _MONTHS[match["month"]], int(match["day"]))
    except ValueError as error:
        raise PageParseError(f"invalid 'Last update' date: {match.group(0)!r}") from error


def parse_page(html: bytes) -> ParsedPage:
    soup = BeautifulSoup(html, "html.parser")
    year = _parse_year(soup)
    last_update = _parse_last_update(soup)

    table = soup.find("table")
    if table is None:
        raise PageParseError("no <table> found")

    entries: list[ParsedEntry] = []
    pending: RtpLabel | None = None
    for cell in table.find_all("td"):
        text = " ".join(cell.get_text().split())
        if not text:
            continue
        if (value := parse_value(text)) is not None:
            if pending is None:
                raise PageParseError(f"index {text!r} has no preceding class label")
            entries.append(ParsedEntry(label=pending, index=value))
            pending = None
            if len(entries) > MAX_CLASSES:
                raise PageParseError(f"implausible class count: more than {MAX_CLASSES}")
        elif (label := parse_label(text)) is not None:
            if pending is not None:
                raise PageParseError(f"label {pending.text!r} has no index value")
            pending = label
        else:
            raise PageParseError(f"unrecognized cell in index table: {text!r}")
    if pending is not None:
        raise PageParseError(f"label {pending.text!r} has no index value")

    if not MIN_CLASSES <= len(entries) <= MAX_CLASSES:
        raise PageParseError(f"implausible class count: {len(entries)}")
    counts = Counter(entry.label.code for entry in entries)
    duplicates = sorted(str(code) for code, count in counts.items() if count > 1)
    if duplicates:
        raise PageParseError(f"duplicate class codes on page: {duplicates}")
    return ParsedPage(year=year, page_last_update=last_update, entries=tuple(entries))


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    body: bytes
    retrieved_at: datetime


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001 - urllib signature
        try:
            parse_source_url(newurl)
        except ValueError:
            raise urllib.error.HTTPError(newurl, code, f"refusing redirect to {newurl!r}", headers, fp) from None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SameOriginRedirectHandler)


class Fetcher:
    """HTTP client honoring solotime.info's robots.txt Crawl-delay."""

    def __init__(self, delay: float = CRAWL_DELAY_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 opener: urllib.request.OpenerDirector = _OPENER,
                 html_dir: Path | None = None) -> None:
        self._opener = opener
        self._html_dir = html_dir
        self._delay = delay
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None

    def _wait_turn(self) -> None:
        if self._last_request is not None:
            remaining = self._delay - (self._clock() - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request = self._clock()

    def get(self, url: str) -> FetchedPage | None:
        """Return the page, or None if it does not exist (HTTP 404)."""
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for attempt in range(MAX_RETRIES + 1):
            self._wait_turn()
            try:
                with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                    final_url = response.geturl()
                    body = self._read_body(url, response)
                break
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                if not (error.code == 429 or error.code >= 500) or attempt == MAX_RETRIES:
                    raise
            except (OSError, http.client.HTTPException):
                if attempt == MAX_RETRIES:
                    raise
            self._sleep(2.0 ** attempt)
        else:
            raise AssertionError("unreachable")
        try:
            parse_source_url(final_url)
        except ValueError as error:
            raise RuntimeError(f"{url}: unexpected final URL {final_url!r}") from error
        page = FetchedPage(url=final_url, body=body, retrieved_at=datetime.now(UTC))
        self._save(page)
        return page

    def _save(self, page: FetchedPage) -> None:
        """Keep the raw page for debugging, before it is parsed (so parse failures can be inspected)."""
        if self._html_dir is None:
            return
        self._html_dir.mkdir(parents=True, exist_ok=True)
        segment = urllib.parse.urlsplit(page.url).path.rsplit("/", 1)[-1]
        name = re.sub(r"[^A-Za-z0-9.-]", "_", segment)[:100] or "index.html"
        stamp = page.retrieved_at.strftime("%Y%m%dT%H%M%SZ")
        (self._html_dir / f"{stamp}-{name}").write_bytes(page.body)

    def _read_body(self, url: str, response: urllib.response.addinfourl) -> bytes:
        deadline = self._clock() + DEADLINE_SECONDS
        chunks: list[bytes] = []
        size = 0
        # read1 returns after a single socket read, so a server trickling bytes cannot outlast the deadline.
        while chunk := response.read1(READ_CHUNK_BYTES):
            if self._clock() > deadline:
                raise TimeoutError(f"{url}: response took longer than {DEADLINE_SECONDS:.0f}s")
            size += len(chunk)
            if size > MAX_PAGE_BYTES:
                raise RuntimeError(f"{url}: response exceeds {MAX_PAGE_BYTES} bytes")
            chunks.append(chunk)
        return b"".join(chunks)


class YearMismatchError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Snapshot:
    page: FetchedPage
    parsed: ParsedPage


def _snapshot(page: FetchedPage) -> Snapshot:
    try:
        return Snapshot(page=page, parsed=parse_page(page.body))
    except PageParseError as error:
        raise PageParseError(f"{page.url}: {error}") from error


def fetch_newest(fetcher: Fetcher) -> Snapshot:
    page = fetcher.get(BASE_URL)
    if page is None:
        raise RuntimeError(f"{BASE_URL} returned 404")
    return _snapshot(page)


def fetch_year(fetcher: Fetcher, year: Year, newest: Snapshot | None = None) -> Snapshot | None:
    """Fetch a specific year from its archive page, falling back to the main page.

    Returns None if the year has not been published yet.
    """
    page = fetcher.get(ARCHIVE_URL.format(year=year))
    if page is not None:
        snapshot = _snapshot(page)
    else:
        snapshot = newest if newest is not None else fetch_newest(fetcher)
        if snapshot.parsed.year != year:
            return None
    if snapshot.parsed.year != year:
        raise YearMismatchError(f"{snapshot.page.url}: requested {year}, page reports {snapshot.parsed.year}")
    return snapshot


@dataclass(frozen=True, slots=True)
class YearChange:
    year: Year
    added: tuple[RtpEntry, ...]
    removed: tuple[RtpEntry, ...]
    changed: tuple[tuple[RtpEntry, RtpEntry], ...]

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


@dataclass(frozen=True, slots=True)
class UpdateResult:
    year: Year
    url: str
    page_last_update: date
    source_changed: bool
    change: YearChange


def _entries_from(parsed: ParsedPage) -> list[RtpEntry]:
    return [RtpEntry(year=parsed.year, code=e.label.code, index=e.index, label=e.label)
            for e in parsed.entries]


def diff_year(year: Year, old: Sequence[RtpEntry], new: Sequence[RtpEntry]) -> YearChange:
    old_by_code = {e.code: e for e in old}
    new_by_code = {e.code: e for e in new}
    return YearChange(
        year=year,
        added=tuple(new_by_code[c] for c in sorted(new_by_code.keys() - old_by_code.keys())),
        removed=tuple(old_by_code[c] for c in sorted(old_by_code.keys() - new_by_code.keys())),
        changed=tuple((old_by_code[c], new_by_code[c]) for c in sorted(old_by_code.keys() & new_by_code.keys())
                      if old_by_code[c] != new_by_code[c]),
    )


def apply_snapshot(snapshot: Snapshot, csv_dir: Path) -> UpdateResult:
    """Replace the snapshot's year in rtp.csv and upsert its sources.csv row.

    Nothing is written when the page body is byte-identical to the recorded one.
    """
    rtp_path = csv_dir / "rtp.csv"
    sources_path = csv_dir / "sources.csv"
    year = snapshot.parsed.year
    entries = read_rtp(rtp_path) if rtp_path.exists() else []
    sources = read_sources(sources_path) if sources_path.exists() else []

    sha = Sha256.parse(hashlib.sha256(snapshot.page.body).hexdigest())
    previous = next((s for s in sources if s.year == year), None)
    old_year = [e for e in entries if e.year == year]
    new_year = _entries_from(snapshot.parsed)

    if previous is not None and previous.sha256 == sha:
        return UpdateResult(year=year, url=snapshot.page.url, page_last_update=previous.page_last_update,
                            source_changed=False, change=diff_year(year, old_year, old_year))

    write_rtp(rtp_path, [e for e in entries if e.year != year] + new_year)
    record = SourceRecord(year=year, url=snapshot.page.url, page_last_update=snapshot.parsed.page_last_update,
                          retrieved_at=snapshot.page.retrieved_at, sha256=sha)
    write_sources(sources_path, [s for s in sources if s.year != year] + [record])
    return UpdateResult(year=year, url=snapshot.page.url, page_last_update=snapshot.parsed.page_last_update,
                        source_changed=True, change=diff_year(year, old_year, new_year))


def unclassified(csv_dir: Path) -> list[RtpEntry]:
    if not (csv_dir / "rtp.csv").exists():
        return []
    classes_path = csv_dir / "classes.csv"
    eras = read_classes(classes_path) if classes_path.exists() else []
    return [e for e in read_rtp(csv_dir / "rtp.csv")
            if sum(1 for era in eras if era.code == e.code and era.covers(e.year)) != 1]


def suggested_lineage(csv_dir: Path, results: Sequence[UpdateResult]) -> list[RtpEntry]:
    """Entries added or changed in this run whose label names a class not yet linked in lineage.csv."""
    lineage_path = csv_dir / "lineage.csv"
    known: set[tuple[ClassCode, ClassCode]] = set()
    if lineage_path.exists():
        for link in read_lineage(lineage_path):
            known |= {(link.code, link.predecessor), (link.predecessor, link.code)}
    touched = [e for r in results for e in (*r.change.added, *(new for _, new in r.change.changed))]
    return [e for e in touched
            if e.label.predecessor is not None and (e.code, e.label.predecessor) not in known]


def render_report(results: Sequence[UpdateResult], unknown: Sequence[RtpEntry],
                  lineage: Sequence[RtpEntry], not_published: Sequence[Year] = ()) -> str:
    lines = ["## PAX/RTP source check", ""]
    for result in results:
        status = "changed" if result.source_changed else "unchanged"
        lines.append(f"### {result.year}: page {status} "
                     f"(last update {result.page_last_update.isoformat()}, <{result.url}>)")
        change = result.change
        if change.is_empty:
            lines.append("- No index changes")
        for e in change.added:
            lines.append(f"- Added `{e.code}` {e.index} (label `{e.label}`)")
        for e in change.removed:
            lines.append(f"- Removed `{e.code}` {e.index}")
        for old, new in change.changed:
            lines.append(f"- Changed `{new.code}` {old.index} → {new.index}"
                         + (f" (label `{old.label}` → `{new.label}`)" if old.label != new.label else ""))
        lines.append("")
    if not_published:
        lines.append("### Not published yet")
        lines.extend(f"- {year}" for year in not_published)
        lines.append("")
    if unknown:
        lines.append("### Needs classification (add rows to `CSV/classes.csv`)")
        lines.extend(f"- `{e.code}` in {e.year}" for e in unknown)
        lines.append("")
    if lineage:
        lines.append("### Suggested lineage (confirm relation in `CSV/lineage.csv`)")
        lines.extend(f"- {e.year} `{e.code}` ← `{e.label.predecessor}` (label `{e.label}`)"
                     for e in lineage)
        lines.append("")
    return "\n".join(lines)


def _year_argument(raw: str) -> Year:
    try:
        value = int(raw)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not a year: {raw!r}") from error
    latest = datetime.now(UTC).year + 1
    if not FIRST_YEAR <= value <= latest:
        raise argparse.ArgumentTypeError(f"year must be from {FIRST_YEAR} to {latest}")
    return Year(value)


def main(argv: Sequence[str] | None = None, fetcher: Fetcher | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("-y", "--year", type=_year_argument, action="append",
                           help="Year to fetch (repeatable). Default: newest published year and the one before it")
    selection.add_argument("--all", action="store_true", help=f"Fetch every year from {FIRST_YEAR}")
    parser.add_argument("--csv-dir", type=Path, default=CSV_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--report", type=Path, help="Write a Markdown change report to this path")
    parser.add_argument("--html-dir", type=Path, help="Save fetched HTML here (for debugging; do not commit)")
    args = parser.parse_args(argv)

    if fetcher is None:
        fetcher = Fetcher(html_dir=args.html_dir)
    newest = fetch_newest(fetcher)
    snapshots: list[Snapshot] = []
    if args.year:
        years = sorted(set(args.year))
    elif args.all:
        years = [Year(y) for y in range(FIRST_YEAR, newest.parsed.year + 1)]
    else:
        years = [Year(newest.parsed.year - 1), newest.parsed.year]

    not_published: list[Year] = []
    for year in years:
        snapshot = newest if year == newest.parsed.year else fetch_year(fetcher, year, newest)
        if snapshot is None:
            print(f"{year}: not published", file=sys.stderr)
            not_published.append(year)
            continue
        snapshots.append(snapshot)

    results = [apply_snapshot(snapshot, args.csv_dir) for snapshot in snapshots]
    report = render_report(results, unclassified(args.csv_dir), suggested_lineage(args.csv_dir, results),
                           not_published)
    print(report)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    return 1 if args.year and not_published else 0


if __name__ == "__main__":
    sys.exit(main())
