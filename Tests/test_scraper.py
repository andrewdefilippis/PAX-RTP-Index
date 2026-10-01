import argparse
import hashlib
import http.client
import io
import urllib.error
import urllib.request
from datetime import UTC, date, datetime

import pytest

import rtp_web_scraper as scraper
from helpers import make_page
from rtp_model import ClassCode, Lineage, LineageRelation, Year, read_rtp, read_sources, write_lineage
from rtp_web_scraper import (
    ARCHIVE_URL,
    BASE_URL,
    USER_AGENT,
    FetchedPage,
    Fetcher,
    PageParseError,
    YearMismatchError,
    apply_snapshot,
    fetch_year,
    main,
    render_report,
    suggested_lineage,
    unclassified,
)

RETRIEVED = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def snapshot(cells, year=2024, last_update="Last update December 20, 2023", url=None):
    body = make_page(cells, header=f"{year} PAX/RTP Index", last_update=last_update)
    page = FetchedPage(url=url or ARCHIVE_URL.format(year=year), body=body, retrieved_at=RETRIEVED)
    return scraper._snapshot(page)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, url: str):
        super().__init__(body)
        self._url = url

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Stands in for urllib's OpenerDirector; each URL maps to a queue of bodies or exceptions."""

    def __init__(self, responses: dict[str, list]):
        self.responses = responses
        self.requests: list[tuple[str, str, float]] = []

    def open(self, request, timeout):
        self.requests.append((request.full_url, request.get_header("User-agent"), timeout))
        outcome = self.responses[request.full_url].pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        body, final_url = outcome if isinstance(outcome, tuple) else (outcome, request.full_url)
        return FakeResponse(body, final_url)


def fetcher_for(responses, **kwargs):
    clock = FakeClock()
    opener = FakeOpener(responses)
    return Fetcher(delay=10.0, clock=clock.clock, sleep=clock.sleep, opener=opener, **kwargs), opener, clock


def http_error(url, code):
    return urllib.error.HTTPError(url, code, "error", {}, None)


URL = "https://www.solotime.info/pax/rtp2024.html"


def test_fetcher_honors_crawl_delay_and_sends_user_agent():
    other = "https://www.solotime.info/pax/"
    fetcher, opener, clock = fetcher_for({URL: [b"one"], other: [b"two"]})
    assert fetcher.get(URL).body == b"one"
    clock.now += 3.0
    assert fetcher.get(other).body == b"two"
    assert clock.sleeps == [7.0]
    assert opener.requests == [(URL, USER_AGENT, 30.0), (other, USER_AGENT, 30.0)]


def test_fetcher_404_means_not_published():
    fetcher, _, _ = fetcher_for({URL: [http_error(URL, 404)]})
    assert fetcher.get(URL) is None


@pytest.mark.parametrize("failure", [
    http_error(URL, 503),
    http_error(URL, 429),
    TimeoutError(),
    ConnectionResetError(),
    http.client.IncompleteRead(b"partial"),
    urllib.error.URLError("dns"),
])
def test_fetcher_retries_transient_errors_with_backoff(failure):
    fetcher, opener, clock = fetcher_for({URL: [failure, b"ok"]})
    assert fetcher.get(URL).body == b"ok"
    assert len(opener.requests) == 2
    assert clock.sleeps == [1.0, 9.0]


def test_fetcher_gives_up_after_retries():
    fetcher, opener, _ = fetcher_for({URL: [http_error(URL, 500)] * 3})
    with pytest.raises(urllib.error.HTTPError):
        fetcher.get(URL)
    assert len(opener.requests) == 3


def test_fetcher_does_not_retry_client_errors():
    fetcher, opener, _ = fetcher_for({URL: [http_error(URL, 403)]})
    with pytest.raises(urllib.error.HTTPError):
        fetcher.get(URL)
    assert len(opener.requests) == 1


def test_fetcher_rejects_oversized_response():
    fetcher, _, _ = fetcher_for({URL: [b"x" * (scraper.MAX_PAGE_BYTES + 1)]})
    with pytest.raises(RuntimeError, match="exceeds"):
        fetcher.get(URL)


class DripResponse(FakeResponse):
    """Each read1 returns one byte and advances the fake clock, like a server trickling data."""

    def __init__(self, clock: "FakeClock", seconds_per_byte: float):
        super().__init__(b"x" * 1000, URL)
        self._clock = clock
        self._seconds_per_byte = seconds_per_byte

    def read1(self, size=-1):
        self._clock.now += self._seconds_per_byte
        return super().read1(1)


def test_fetcher_deadline_stops_slow_drip():
    clock = FakeClock()

    class DripOpener:
        def open(self, request, timeout):
            return DripResponse(clock, 1.0)

    fetcher = Fetcher(clock=clock.clock, sleep=clock.sleep, opener=DripOpener())
    with pytest.raises(TimeoutError, match="longer than 60s"):
        fetcher.get(URL)
    assert clock.now < 400


def test_fetcher_saved_name_is_sanitized_and_truncated(tmp_path):
    long_url = "https://www.solotime.info/pax/" + "a" * 300 + ".html"
    fetcher, _, _ = fetcher_for({long_url: [b"ok"]}, html_dir=tmp_path)
    fetcher.get(long_url)
    (saved,) = tmp_path.iterdir()
    stamp, name = saved.name.split("-", 1)
    assert len(stamp) == len("20261001T120000Z")
    assert name == "a" * 100


def test_fetcher_save_failure_is_not_retried(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    fetcher, opener, _ = fetcher_for({URL: [b"ok"]}, html_dir=blocker)
    with pytest.raises(OSError):
        fetcher.get(URL)
    assert len(opener.requests) == 1


def test_fetcher_records_final_url_and_rejects_foreign_host():
    fetcher, _, _ = fetcher_for({URL: [(b"ok", "https://www.solotime.info/pax/moved.html")],
                                 BASE_URL: [(b"bad", "https://evil.example/pax/")]})
    assert fetcher.get(URL).url == "https://www.solotime.info/pax/moved.html"
    with pytest.raises(RuntimeError, match="unexpected final URL"):
        fetcher.get(BASE_URL)


@pytest.mark.parametrize(("target", "allowed"), [
    ("https://www.solotime.info/pax/rtp2024.html", True),
    ("http://www.solotime.info/pax/rtp2024.html", False),
    ("https://www.solotime.info:8080/pax/rtp2024.html", False),
    ("https://www.solotime.info/pax/x.html?a=<b>", False),
    ("https://evil.example/pax/rtp2024.html", False),
    ("ftp://www.solotime.info/x", False),
])
def test_redirect_policy(target, allowed):
    handler = scraper._SameOriginRedirectHandler()
    request = urllib.request.Request(URL)
    if allowed:
        assert handler.redirect_request(request, None, 302, "Found", {}, target).full_url == target
    else:
        with pytest.raises(urllib.error.HTTPError, match="refusing redirect"):
            handler.redirect_request(request, None, 302, "Found", {}, target)


def test_fetcher_saves_html_before_parsing(tmp_path):
    fetcher, _, _ = fetcher_for({URL: [b"<html>not a pax page</html>"]}, html_dir=tmp_path)
    page = fetcher.get(URL)
    with pytest.raises(PageParseError):
        scraper._snapshot(page)
    (saved,) = tmp_path.iterdir()
    assert saved.name.endswith("-rtp2024.html")
    assert saved.read_bytes() == b"<html>not a pax page</html>"


class StubFetcher:
    def __init__(self, pages: dict[str, bytes | None]):
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url):
        self.requested.append(url)
        body = self.pages[url]
        return None if body is None else FetchedPage(url=url, body=body, retrieved_at=RETRIEVED)


def page_for(year, cells=()):
    return make_page(list(cells), header=f"{year} PAX/RTP Index", last_update="Last update March 20, 2026")


def test_fetch_year_uses_archive_page():
    fetcher = StubFetcher({ARCHIVE_URL.format(year=2024): page_for(2024)})
    assert fetch_year(fetcher, Year(2024)).parsed.year == 2024


def test_fetch_year_not_yet_published_falls_back_to_main_page():
    fetcher = StubFetcher({ARCHIVE_URL.format(year=2027): None, BASE_URL: page_for(2026)})
    assert fetch_year(fetcher, Year(2027)) is None
    assert fetcher.requested == [ARCHIVE_URL.format(year=2027), BASE_URL]


def test_fetch_year_rejects_mismatched_archive_page():
    fetcher = StubFetcher({ARCHIVE_URL.format(year=2024): page_for(2023)})
    with pytest.raises(YearMismatchError, match="requested 2024, page reports 2023"):
        fetch_year(fetcher, Year(2024))


def test_apply_snapshot_replaces_whole_year(tmp_path):
    apply_snapshot(snapshot([("SS", "0.840")], year=2023, last_update="Last update December 25 2022"), tmp_path)
    apply_snapshot(snapshot([("XS", "0.852"), ("SSR", "0.846"), ("EVX", "0.830")],
                            last_update="Last update December 10, 2023"), tmp_path)

    revised = snapshot([("XU", "0.869"), ("EVX", "0.834")])
    result = apply_snapshot(revised, tmp_path)

    rows = {(e.year, str(e.code)): str(e.index) for e in read_rtp(tmp_path / "rtp.csv")}
    assert rows[(2023, "SS")] == "0.840"
    assert rows[(2024, "XU")] == "0.869"
    assert rows[(2024, "EVX")] == "0.834"
    assert (2024, "XS") not in rows and (2024, "SSR") not in rows
    assert [str(e.code) for e in result.change.added] == ["XU"]
    assert [str(e.code) for e in result.change.removed] == ["SSR", "XS"]
    assert [(str(o.index), str(n.index)) for o, n in result.change.changed] == [("0.830", "0.834")]

    record = next(s for s in read_sources(tmp_path / "sources.csv") if s.year == 2024)
    assert record.page_last_update == date(2023, 12, 20)
    assert str(record.sha256) == hashlib.sha256(revised.page.body).hexdigest()


def test_apply_snapshot_unchanged_page_writes_nothing(tmp_path):
    snap = snapshot([("SS", "0.840")])
    apply_snapshot(snap, tmp_path)
    before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.iterdir()}
    result = apply_snapshot(snap, tmp_path)
    assert not result.source_changed
    assert result.change.is_empty
    assert {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.iterdir()} == before


def test_unclassified(tmp_path):
    apply_snapshot(snapshot([("AST(STR)", "0.834"), ("BST(STU)", "0.833")], year=2025,
                            last_update="Last update January 14, 2025"), tmp_path)
    (tmp_path / "classes.csv").write_text("class,first_year,last_year,name,category,status,source\n"
                                          "AST,2025,,A Street Touring,Street Touring,verified,test\n")
    unknown = {str(e.code) for e in unclassified(tmp_path)}
    assert "BST" in unknown and "AST" not in unknown


def test_lineage_suggestions_only_for_this_runs_unlinked_labels(tmp_path):
    write_lineage(tmp_path / "lineage.csv",
                  [Lineage(Year(2025), ClassCode("AST"), ClassCode("STR"), LineageRelation.DERIVED, "test"),
                   Lineage(Year(2008), ClassCode("FJB"), ClassCode("FJ3"), LineageRelation.DERIVED, "test")])
    apply_snapshot(snapshot([("FJ3 (FJB)", "0.830")], year=2007, last_update="Last update November 21, 2006"),
                   tmp_path)
    result = apply_snapshot(snapshot([("AST(STR)", "0.836"), ("BST(STU)", "0.835")], year=2026,
                                     last_update="Last update March 20, 2026"), tmp_path)
    assert [(str(e.code), str(e.label)) for e in suggested_lineage(tmp_path, [result])] == [("BST", "BST(STU)")]


def test_report_lists_changes(tmp_path):
    apply_snapshot(snapshot([("XS", "0.852"), ("EVX", "0.830")]), tmp_path)
    result = apply_snapshot(snapshot([("XU", "0.869"), ("EVX", "0.834")]), tmp_path)
    report = render_report([result], unclassified(tmp_path), suggested_lineage(tmp_path, [result]), [Year(2027)])
    assert "### 2024: page changed (last update 2023-12-20" in report
    assert "- Added `XU` 0.869 (label `XU`)" in report
    assert "- Removed `XS` 0.852" in report
    assert "- Changed `EVX` 0.830 → 0.834" in report
    assert "### Not published yet\n- 2027" in report
    assert "### Needs classification" in report
    assert "- `XU` in 2024" in report


def test_main_weekly_mode_applies_newest_and_previous_year(tmp_path):
    fetcher = StubFetcher({BASE_URL: page_for(2026, [("AST(STR)", "0.836")]),
                           ARCHIVE_URL.format(year=2025): page_for(2025, [("AST(STR)", "0.834")])})
    report = tmp_path / "report.md"
    assert main(["--csv-dir", str(tmp_path), "--report", str(report)], fetcher=fetcher) == 0
    assert fetcher.requested == [BASE_URL, ARCHIVE_URL.format(year=2025)]
    assert {e.year for e in read_rtp(tmp_path / "rtp.csv")} == {2025, 2026}
    assert {s.url for s in read_sources(tmp_path / "sources.csv")} == {BASE_URL, ARCHIVE_URL.format(year=2025)}
    assert "### 2026: page changed" in report.read_text()


def test_main_weekly_mode_reports_unpublished_previous_year(tmp_path):
    fetcher = StubFetcher({BASE_URL: page_for(2027), ARCHIVE_URL.format(year=2026): None})
    report = tmp_path / "report.md"
    assert main(["--csv-dir", str(tmp_path), "--report", str(report)], fetcher=fetcher) == 0
    assert "### Not published yet\n- 2026" in report.read_text()


def test_main_explicit_unpublished_year_fails(tmp_path):
    fetcher = StubFetcher({BASE_URL: page_for(2026), ARCHIVE_URL.format(year=2027): None})
    assert main(["--csv-dir", str(tmp_path), "--year", "2027"], fetcher=fetcher) == 1


def test_main_all_fetches_every_year(tmp_path):
    pages = {BASE_URL: page_for(2026)}
    pages |= {ARCHIVE_URL.format(year=y): page_for(y) for y in range(1995, 2026)}
    fetcher = StubFetcher(pages)
    assert main(["--csv-dir", str(tmp_path), "--all"], fetcher=fetcher) == 0
    assert len(fetcher.requested) == 32
    assert [s.year for s in read_sources(tmp_path / "sources.csv")] == list(range(1995, 2027))


def test_year_argument_bounds():
    with pytest.raises(argparse.ArgumentTypeError, match="year must be from 1995"):
        scraper._year_argument("1994")
    with pytest.raises(argparse.ArgumentTypeError, match="not a year"):
        scraper._year_argument("20x4")
    assert scraper._year_argument("2024") == 2024
