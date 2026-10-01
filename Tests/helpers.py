from datetime import UTC, date, datetime
from pathlib import Path

from rtp_model import (
    Category,
    ClassCode,
    ClassEra,
    IndexValue,
    RtpEntry,
    RtpLabel,
    Sha256,
    SourceRecord,
    Verification,
    Year,
    write_classes,
    write_lineage,
    write_rtp,
    write_sources,
)

SHA = Sha256("0" * 64)
FILLER = [(f"F{n}", "0.850") for n in range(20)]


def make_page(cells: list[tuple[str, str] | str], *, header: str = "2009 PAX/RTP Index",
              last_update: str = "Last update November 14, 2008", filler: bool = True) -> bytes:
    flat: list[str] = []
    for cell in cells:
        flat.extend(cell if isinstance(cell, tuple) else (cell,))
    if filler:
        for label, value in FILLER:
            flat.extend((label, value, ""))
    tds = "".join(f"<td>{text}</td>" for text in flat)
    return (f"<html><body><h1>{header}</h1><table><tr>{tds}</tr></table>"
            f"<p>{last_update}</p></body></html>").encode()


def entry(year: int, code: str, index: str = "0.850", label: str | None = None) -> RtpEntry:
    return RtpEntry(Year(year), ClassCode(code), IndexValue.parse(index), RtpLabel.parse(label or code))


def era(code: str, first: int, last: int | None, category: Category = Category.STREET,
        status: Verification = Verification.VERIFIED) -> ClassEra:
    return ClassEra(ClassCode(code), Year(first), None if last is None else Year(last),
                    f"{code} name", category, status, "test")


def source(year: int) -> SourceRecord:
    return SourceRecord(Year(year), f"https://www.solotime.info/pax/rtp{year}.html", date(year - 1, 12, 1),
                        datetime(2026, 10, 1, 12, 0, tzinfo=UTC), SHA)


def write_dataset(directory: Path, entries, eras, lineage=(), sources=None) -> None:
    write_rtp(directory / "rtp.csv", entries)
    write_classes(directory / "classes.csv", eras)
    write_lineage(directory / "lineage.csv", lineage)
    years = sorted({e.year for e in entries})
    write_sources(directory / "sources.csv", sources if sources is not None else [source(y) for y in years])
