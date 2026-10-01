from decimal import Decimal

import pytest

from helpers import SHA, entry, era, source, write_dataset
from rtp_model import (
    Category,
    ClassCode,
    ClassEra,
    CsvFormatError,
    Dataset,
    DatasetError,
    IndexValue,
    Lineage,
    LineageRelation,
    RtpEntry,
    RtpLabel,
    Verification,
    Year,
    parse_year,
    read_classes,
    read_rtp,
    read_sources,
    write_classes,
    write_lineage,
    write_rtp,
    write_sources,
)

@pytest.mark.parametrize("raw", ["1995", "2026"])
def test_parse_year(raw):
    assert parse_year(raw) == int(raw)


@pytest.mark.parametrize("raw", ["1994", "95", "2026a", "", " 2026", "\u0662\u0660\u0662\u0665"])
def test_parse_year_rejects(raw):
    with pytest.raises(ValueError, match="invalid year"):
        parse_year(raw)


@pytest.mark.parametrize("raw", ["0.820", "1.000", "0.8235", "1.0000"])
def test_index_value_preserves_published_text(raw):
    assert str(IndexValue.parse(raw)) == raw


@pytest.mark.parametrize("raw", ["0.82", "1.001", "1", ".820", "0.82000", "-0.820"])
def test_index_value_rejects(raw):
    with pytest.raises(ValueError, match="invalid index value"):
        IndexValue.parse(raw)


@pytest.mark.parametrize("raw", ["", "ast", "AST(STR)", "A S", "ABCDEFGHI", "-AS"])
def test_class_code_rejects(raw):
    with pytest.raises(ValueError, match="invalid class code"):
        ClassCode.parse(raw)


def test_rtp_round_trip_is_sorted_and_exact(tmp_path):
    path = tmp_path / "rtp.csv"
    write_rtp(path, [entry(2025, "AST", "0.834", "AST(STR)"), entry(1995, "SS", "0.840"), entry(1995, "AM", "1.000")])
    assert path.read_text() == (
        "year,class,index,label\n"
        "1995,AM,1.000,AM\n"
        "1995,SS,0.840,SS\n"
        "2025,AST,0.834,AST(STR)\n"
    )
    entries = read_rtp(path)
    assert entries[1].index.value == Decimal("0.840")
    assert entries[2].label == RtpLabel.parse("AST(STR)")
    assert entries[2].label.predecessor == ClassCode("STR")


def test_csv_errors_name_file_and_line(tmp_path):
    path = tmp_path / "rtp.csv"
    path.write_text("year,class,index,label\n1995,SS,0.840,SS\n1995,AS,0.83,AS\n")
    with pytest.raises(CsvFormatError, match=r"rtp\.csv:3: invalid index value: '0\.83'"):
        read_rtp(path)


def test_csv_rejects_wrong_header(tmp_path):
    path = tmp_path / "rtp.csv"
    path.write_text("year,class,value,label\n")
    with pytest.raises(CsvFormatError, match=r"rtp\.csv:1: expected header year,class,index,label"):
        read_rtp(path)


def test_csv_rejects_wrong_field_count(tmp_path):
    path = tmp_path / "rtp.csv"
    path.write_text("year,class,index,label\n1995,SS,0.840\n")
    with pytest.raises(CsvFormatError, match=r"rtp\.csv:2: wrong number of fields"):
        read_rtp(path)


def test_classes_reject_unknown_category(tmp_path):
    path = tmp_path / "classes.csv"
    path.write_text("class,first_year,last_year,name,category,status,source\nSS,1995,,Super Street,Streets,verified,x\n")
    with pytest.raises(CsvFormatError, match=r"classes\.csv:2: 'Streets' is not a valid Category"):
        read_classes(path)


def test_classes_open_ended_era_round_trip(tmp_path):
    path = tmp_path / "classes.csv"
    write_classes(path, [era("SS", 2012, None), era("SS", 1995, 2011, Category.STOCK)])
    eras = read_classes(path)
    assert [(e.first_year, e.last_year, e.category) for e in eras] == [
        (1995, 2011, Category.STOCK), (2012, None, Category.STREET)]


def test_sources_round_trip(tmp_path):
    path = tmp_path / "sources.csv"
    write_sources(path, [source(2024)])
    assert path.read_text().splitlines()[1] == (
        f"2024,https://www.solotime.info/pax/rtp2024.html,2023-12-01,2026-10-01T12:00:00Z,{'0' * 64}")
    assert read_sources(path) == [source(2024)]


@pytest.mark.parametrize("url", [
    "http://www.solotime.info/pax/rtp2024.html",
    "https://evil.example/pax/rtp2024.html",
    "https://www.solotime.info:8443/pax/rtp2024.html",
    "https://user@www.solotime.info/pax/rtp2024.html",
    "https://www.solotime.info/pax/rtp2024.html?x=1",
    "https://www.solotime.info/pax/rtp2024.html#top",
    "https://www.solotime.info/other/rtp2024.html",
    "https://www.solotime.info/pax/<b>.html",
    " https://www.solotime.info/pax/",
    "https://www.solotime.info/pax/rtp\\n2025.html",
    "https://www.solotime.info/pax/..",
    "https://www.solotime.info/pax/sub/x.html",
])
def test_sources_reject_non_source_urls(tmp_path, url):
    path = tmp_path / "sources.csv"
    path.write_text(f"year,url,page_last_update,retrieved_at,sha256\n2024,{url},2023-12-01,2026-10-01T12:00:00Z,{'0' * 64}\n")
    with pytest.raises(CsvFormatError, match="not a www.solotime.info/pax/ page URL"):
        read_sources(path)


@pytest.mark.parametrize("text", ["A\u202eB", "zero\u200bwidth", "line\u2028sep", "c1\x85ctl"])
def test_free_text_rejects_invisible_unicode(tmp_path, text):
    path = tmp_path / "classes.csv"
    path.write_text(f"class,first_year,last_year,name,category,status,source\nSS,1995,,{text},Street,verified,x\n")
    with pytest.raises(CsvFormatError, match="name contains disallowed characters"):
        read_classes(path)


def test_csv_write_refuses_symlink(tmp_path):
    target = tmp_path / "target.csv"
    target.write_text("untouched")
    (tmp_path / "rtp.csv").symlink_to(target)
    with pytest.raises(RuntimeError, match="refusing to write through symlink"):
        write_rtp(tmp_path / "rtp.csv", [])
    assert target.read_text() == "untouched"


def test_dataset_valid(tmp_path):
    write_dataset(tmp_path, [entry(2024, "STR"), entry(2025, "AST", label="AST(STR)")],
                  [era("STR", 1999, 2024, Category.STREET_TOURING), era("AST", 2025, None, Category.STREET_TOURING)],
                  [Lineage(Year(2025), ClassCode("AST"), ClassCode("STR"), LineageRelation.DERIVED, "test")])
    dataset = Dataset.load(tmp_path)
    assert dataset.years() == [2024, 2025]
    assert dataset.era_for(ClassCode("AST"), Year(2026)).category is Category.STREET_TOURING


def test_dataset_reports_every_problem(tmp_path):
    write_dataset(
        tmp_path,
        [entry(2024, "SS"), entry(2024, "XX"), entry(2025, "SS")],
        [era("SS", 1995, 2024), era("SS", 2024, None), era("YY", 2000, 1999)],
        [Lineage(Year(2025), ClassCode("ZZ"), ClassCode("SS"), LineageRelation.RENAMED, "t"),
         Lineage(Year(2024), ClassCode("SS"), ClassCode("XX"), LineageRelation.RENAMED, "t")],
        sources=[source(2024), source(2024)],
    )
    with pytest.raises(DatasetError) as caught:
        Dataset.load(tmp_path)
    assert set(caught.value.problems) == {
        "classes.csv: YY era 2000-1999 ends before it starts",
        "classes.csv: SS eras starting 1995 and 2024 overlap",
        "classes.csv: SS in 2024 is covered by 2 eras (expected 1)",
        "classes.csv: XX in 2024 is covered by 0 eras (expected 1)",
        "lineage.csv: ZZ has no rtp.csv entry in 2025",
        "lineage.csv: predecessor XX has no rtp.csv entry before 2024",
        "sources.csv: 2024 appears 2 times",
        "sources.csv: no source record for 2025",
    }


def test_dataset_rejects_duplicate_entries(tmp_path):
    write_dataset(tmp_path, [entry(2024, "SS"), entry(2024, "SS", "0.851")], [era("SS", 1995, None)])
    with pytest.raises(DatasetError, match="rtp.csv: SS appears 2 times in 2024"):
        Dataset.load(tmp_path)


def test_class_era_allows_unknown_only_when_unverified(tmp_path):
    path = tmp_path / "classes.csv"
    path.write_text("class,first_year,last_year,name,category,status,source\n"
                    "T-1,1998,1998,,,unverified,no 1998 rulebook\n")
    (unknown,) = read_classes(path)
    assert unknown.name is None and unknown.category is None
    assert unknown.status is Verification.UNVERIFIED
    write_classes(path, [unknown])
    assert path.read_text().splitlines()[1] == "T-1,1998,1998,,,unverified,no 1998 rulebook"

    path.write_text("class,first_year,last_year,name,category,status,source\nT-1,1998,1998,,,verified,1998 rules\n")
    with pytest.raises(CsvFormatError, match=r"classes\.csv:2: T-1: unknown name/category requires status 'unverified'"):
        read_classes(path)


@pytest.mark.parametrize("text", ["=HYPERLINK(\"http://x\")", "+1", "-1", "@SUM(A1)", "<img src=x>", "a`b", "tab\there"])
def test_free_text_rejects_formulas_and_markup(tmp_path, text):
    path = tmp_path / "classes.csv"
    path.write_text("class,first_year,last_year,name,category,status,source\n"
                    f"SS,1995,,Super Street,Street,verified,\"{text.replace(chr(34), chr(34) * 2)}\"\n")
    with pytest.raises(CsvFormatError, match="source contains disallowed characters"):
        read_classes(path)


@pytest.mark.parametrize("label", ["AS (", "as", "AS\u00a0(STR)", "=AS"])
def test_rtp_label_rejects(tmp_path, label):
    path = tmp_path / "rtp.csv"
    path.write_text(f"year,class,index,label\n2025,AS,0.830,{label}\n")
    with pytest.raises(CsvFormatError, match="invalid class label"):
        read_rtp(path)


def test_rtp_label_must_match_class(tmp_path):
    path = tmp_path / "rtp.csv"
    path.write_text("year,class,index,label\n2025,AST,0.834,BST(STU)\n")
    with pytest.raises(CsvFormatError, match=r"rtp\.csv:2: label 'BST\(STU\)' does not match class AST"):
        read_rtp(path)


def test_dataset_rejects_empty(tmp_path):
    write_dataset(tmp_path, [], [])
    with pytest.raises(DatasetError, match="rtp.csv: no entries"):
        Dataset.load(tmp_path)
