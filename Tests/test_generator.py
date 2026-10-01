import json
from decimal import Decimal
from pathlib import Path

import jsonschema
import pytest
import yaml

from rtp_files_generator import build, main, write_outputs
from rtp_model import REPO_ROOT, Category, ClassCode, Dataset, Lineage, LineageRelation, Verification, Year
from helpers import entry, era, write_dataset

SCHEMAS = REPO_ROOT / "Schema"


def validator(name: str) -> jsonschema.Draft202012Validator:
    schema = json.loads((SCHEMAS / name).read_text())
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


@pytest.fixture
def root(tmp_path: Path) -> Path:
    write_dataset(
        tmp_path / "CSV",
        [entry(2024, "STR", "0.830"), entry(2024, "AM", "1.000"), entry(2024, "SS", "0.820"),
         entry(2025, "AST", "0.834", "AST(STR)"), entry(2025, "CST", "0.829"), entry(2025, "AM", "1.000"),
         entry(2025, "SS", "0.8235")],
        [era("STR", 1999, 2024, Category.STREET_TOURING), era("AST", 2025, None, Category.STREET_TOURING),
         era("CST", 2025, None, Category.STREET_TOURING), era("AM", 1995, None, Category.MODIFIED),
         era("SS", 1995, 2024, Category.STOCK, Verification.UNVERIFIED), era("SS", 2025, None, Category.STREET)],
        [Lineage(Year(2025), ClassCode("AST"), ClassCode("STR"), LineageRelation.DERIVED, "t"),
         Lineage(Year(2025), ClassCode("CST"), ClassCode("STR"), LineageRelation.DERIVED, "t")],
    )
    return tmp_path


def test_year_files_keep_existing_shape(root):
    assert main(["--root", str(root)]) == 0
    document = json.loads((root / "JSON" / "2025.json").read_text())
    assert document == {"2025": {"AM": 1.0, "AST": 0.834, "CST": 0.829, "SS": 0.8235}}
    validator("rtp-year.schema.json").validate(document)


def test_yaml_year_key_is_a_string(root):
    main(["--root", str(root)])
    document = yaml.safe_load((root / "YAML" / "2024.yaml").read_text())
    assert list(document) == ["2024"]
    assert document["2024"]["SS"] == 0.82


def test_latest_is_newest_year(root):
    main(["--root", str(root)])
    assert (root / "JSON" / "latest.json").read_text() == (root / "JSON" / "2025.json").read_text()
    assert yaml.safe_load((root / "YAML" / "latest.yaml").read_text()) == \
        json.loads((root / "JSON" / "2025.json").read_text())


def test_index_float_round_trip_is_exact():
    dataset = Dataset.load(REPO_ROOT / "CSV")
    assert dataset.entries
    for e in dataset.entries:
        assert Decimal(repr(float(e.index.value))) == e.index.value


def test_combined_document(root):
    main(["--root", str(root)])
    document = json.loads((root / "rtp.json").read_text())
    validator("rtp.schema.json").validate(document)
    assert document["SchemaVersion"] == 2
    assert set(document["Years"]) == {"2024", "2025"}
    classes = document["SoloClasses"]
    assert classes["SS"]["RTP"] == {
        "2024": {"Index": 0.82, "Name": "SS name", "SoloCategory": "Stock", "ClassificationVerified": False},
        "2025": {"Index": 0.8235, "Name": "SS name", "SoloCategory": "Street", "ClassificationVerified": True},
    }
    assert classes["AST"]["Predecessors"] == [{"Year": 2025, "Class": "STR", "Relation": "derived"}]
    assert classes["STR"]["Successors"] == [
        {"Year": 2025, "Class": "AST", "Relation": "derived"},
        {"Year": 2025, "Class": "CST", "Relation": "derived"},
    ]
    assert classes["AM"]["Predecessors"] == [] and classes["AM"]["Successors"] == []
    assert yaml.safe_load((root / "rtp.yaml").read_text()) == document


def test_predecessors_and_successors_are_symmetric(root):
    classes = json.loads(build(Dataset.load(root / "CSV"))[Path("rtp.json")])["SoloClasses"]
    forward = {(c, p["Class"], p["Year"], p["Relation"]) for c, v in classes.items() for p in v["Predecessors"]}
    backward = {(s["Class"], c, s["Year"], s["Relation"]) for c, v in classes.items() for s in v["Successors"]}
    assert forward == backward and forward


def test_generation_is_idempotent(root):
    main(["--root", str(root)])
    first = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    main(["--root", str(root)])
    second = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert first == second


def test_stale_year_files_are_removed(root):
    (root / "JSON").mkdir()
    (root / "JSON" / "1999.json").write_text("{}")
    (root / "JSON" / "README.md").write_text("keep")
    main(["--root", str(root)])
    assert not (root / "JSON" / "1999.json").exists()
    assert (root / "JSON" / "README.md").read_text() == "keep"


def test_invalid_dataset_fails_without_writing(root, capsys):
    (root / "CSV" / "classes.csv").write_text("class,first_year,last_year,name,category,status,source\n")
    assert main(["--root", str(root)]) == 1
    assert "STR in 2024 is covered by 0 eras" in capsys.readouterr().err
    assert not (root / "JSON").exists()


def test_write_outputs_only_touches_generated_paths(tmp_path):
    write_outputs(tmp_path, {Path("JSON") / "2025.json": "{}\n"})
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == ["JSON/2025.json"]


def test_repository_outputs_are_up_to_date():
    """The checked-in JSON/YAML must be exactly what the CSVs generate."""
    for relative, content in build(Dataset.load(REPO_ROOT / "CSV")).items():
        assert (REPO_ROOT / relative).read_text(encoding="utf-8") == content, relative


def test_malformed_csv_fails_without_traceback(root, capsys):
    (root / "CSV" / "rtp.csv").write_text("year,class,index,label\n2024,SS,0.82,SS\n")
    assert main(["--root", str(root)]) == 1
    assert "rtp.csv:2: invalid index value: '0.82'" in capsys.readouterr().err


def test_refuses_to_write_through_symlink(root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "target.json"
    outside.write_text("untouched")
    (root / "JSON").mkdir()
    (root / "JSON" / "2025.json").symlink_to(outside)
    with pytest.raises(RuntimeError, match="refusing to write through symlink"):
        main(["--root", str(root)])
    assert outside.read_text() == "untouched"


def test_repository_classification_is_consistent():
    """Every class-year has one era; eras only span years with data; open eras belong to current classes."""
    dataset = Dataset.load(REPO_ROOT / "CSV")
    years_by_code: dict[ClassCode, set[int]] = {}
    for e in dataset.entries:
        years_by_code.setdefault(e.code, set()).add(e.year)
    newest = max(dataset.years())
    for era_ in dataset.eras:
        years = years_by_code[era_.code]
        assert any(era_.covers(y) for y in years), era_
        if era_.last_year is None:
            assert newest in years, era_
        if era_.category is None:
            assert era_.status is Verification.UNVERIFIED, era_
