from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from rtp_model import ClassCode
from helpers import make_page
from rtp_web_scraper import PageParseError, parse_label, parse_page, parse_value

FIXTURES = Path(__file__).parent / "fixtures"


def entries_by_code(html: bytes) -> dict[str, tuple[str, str]]:
    page = parse_page(html)
    return {str(e.label.code): (str(e.index), e.label.text) for e in page.entries}


def test_modern_layout_fixture():
    page = parse_page((FIXTURES / "modern_layout.html").read_bytes())
    assert page.year == 2026
    assert page.page_last_update == date(2026, 3, 20)
    assert len(page.entries) == 18
    by_code = {str(e.label.code): e for e in page.entries}
    assert by_code["AM"].index.value == Decimal("1.000")
    assert str(by_code["SS"].index) == "0.840"
    assert by_code["CAM-T"].label.predecessor is None
    ast = by_code["AST"]
    assert ast.label.text == "AST(STR)"
    assert ast.label.predecessor == ClassCode("STR")
    assert str(ast.index) == "0.836"


def test_pre_2002_heading_without_pax():
    page = parse_page(make_page([("SS", "0.842")], header="1995 RTP Index",
                                last_update="Last update May 31, 1995"))
    assert page.year == 1995
    assert page.page_last_update == date(1995, 5, 31)


def test_last_update_without_comma():
    page = parse_page(make_page([], last_update="Last update December 25 2022"))
    assert page.page_last_update == date(2022, 12, 25)


@pytest.mark.parametrize(("text", "code", "predecessor", "footnote"), [
    ("SS", "SS", None, False),
    ("T-1", "T-1", None, False),
    ("CAM-C", "CAM-C", None, False),
    ("XS-A", "XS-A", None, False),
    ("FJr", "FJr", None, False),
    ("F125", "F125", None, False),
    ("ST (STS)", "ST", "STS", False),
    ("AST(STR)", "AST", "STR", False),
    ("AS*", "AS", None, True),
])
def test_parse_label(text, code, predecessor, footnote):
    label = parse_label(text)
    assert label is not None
    assert label.code == ClassCode(code)
    assert label.predecessor == (ClassCode(predecessor) if predecessor else None)
    assert label.footnote is footnote
    assert label.text == text


@pytest.mark.parametrize("text", ["Champ Tour", "2026 Indexed Results", "ss", "AS (", "AS (sts)", "0.840"])
def test_parse_label_rejects(text):
    assert parse_label(text) is None


@pytest.mark.parametrize(("text", "expected"), [
    ("0.840", "0.840"),
    ("1.000", "1.000"),
    (".826", "0.826"),
    ("0.989.", "0.989"),
    ("0.8235", "0.8235"),
])
def test_parse_value(text, expected):
    value = parse_value(text)
    assert value is not None
    assert str(value) == expected


@pytest.mark.parametrize("text", ["0.84", "1.5", "0.84x", "SS", "2.000", "\u0660.840"])
def test_parse_value_rejects(text):
    assert parse_value(text) is None


def test_parse_value_out_of_range():
    with pytest.raises(PageParseError, match="invalid index value: '1.234'"):
        parse_value("1.234")


def test_labels_preserved_verbatim():
    by_code = entries_by_code(make_page([("ST (STS)", "0.818"), ("STS (STS2)", "0.820"), ("AS*", "0.854")]))
    assert by_code["ST"] == ("0.818", "ST (STS)")
    assert by_code["STS"] == ("0.820", "STS (STS2)")
    assert by_code["AS"] == ("0.854", "AS*")


def test_trailing_period_value():
    assert entries_by_code(make_page([("FSAE", "0.989.")]))["FSAE"] == ("0.989", "FSAE")


def test_orphan_value():
    with pytest.raises(PageParseError, match="index '0.818' has no preceding class label"):
        parse_page(make_page(["0.818"]))


def test_orphan_label_followed_by_label():
    with pytest.raises(PageParseError, match="label 'ST' has no index value"):
        parse_page(make_page(["ST", "SS", "0.840"]))


def test_orphan_label_at_end():
    with pytest.raises(PageParseError, match="label 'ZZ' has no index value"):
        parse_page(make_page([("SS", "0.840"), "ZZ"], filler=False))


def test_duplicate_code():
    with pytest.raises(PageParseError, match=r"duplicate class codes on page: \['SS'\]"):
        parse_page(make_page([("SS", "0.840"), ("SS", "0.841")]))


def test_unrecognized_cell():
    with pytest.raises(PageParseError, match="unrecognized cell in index table: 'see note'"):
        parse_page(make_page([("SS", "0.840"), "see note"]))


def test_missing_heading():
    with pytest.raises(PageParseError, match="expected exactly one '<year> PAX/RTP Index' heading"):
        parse_page(make_page([], header="PAX Index"))


def test_missing_last_update():
    with pytest.raises(PageParseError, match="expected exactly one 'Last update' date, found 0"):
        parse_page(make_page([], last_update="Updated recently"))


def test_invalid_last_update_date():
    with pytest.raises(PageParseError, match="invalid 'Last update' date"):
        parse_page(make_page([], last_update="Last update February 30, 2020"))


def test_implausible_class_count():
    with pytest.raises(PageParseError, match="implausible class count: 2"):
        parse_page(make_page([("SS", "0.840"), ("AS", "0.830")], filler=False))


def test_no_table():
    html = b"<html><h1>2009 PAX/RTP Index</h1><p>Last update November 14, 2008</p></html>"
    with pytest.raises(PageParseError, match="no <table> found"):
        parse_page(html)


def test_implausible_class_count_stops_early():
    cells = [(f"C{n}", "0.850") for n in range(200)]
    with pytest.raises(PageParseError, match="implausible class count: more than 80"):
        parse_page(make_page(cells, filler=False))


def test_heading_requires_ascii_digits():
    with pytest.raises(PageParseError, match="heading"):
        parse_page(make_page([], header="\u0662\u0660\u0660\u0669 PAX/RTP Index"))


@pytest.mark.parametrize("year", ["1994", "9999"])
def test_page_year_out_of_range(year):
    with pytest.raises(PageParseError, match=f"page year {year} is outside 1995-"):
        parse_page(make_page([], header=f"{year} PAX/RTP Index"))
