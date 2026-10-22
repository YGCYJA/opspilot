"""Check that the published example produces actual passing/failing evidence."""
import importlib.util
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_demo():
    spec = importlib.util.spec_from_file_location("reproduce_pytest_demo",
                                                 ROOT / "scripts" / "reproduce_pytest_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_has_a_passing_baseline_and_real_boundary_failure(tmp_path):
    output = tmp_path / "demo"
    metadata = load_demo().reproduce_demo(output)
    assert metadata["data_kind"] == "deliberately_introduced_regression"
    assert metadata["baseline"] == {"exit_code": 0, "tests": 5, "failures": 0,
                                     "errors": 0, "skipped": 0}
    assert metadata["regression"] == {"exit_code": 1, "tests": 5, "failures": 1,
                                       "errors": 0, "skipped": 0}
    cases = ET.parse(output / "junit.xml").getroot().findall(".//testcase")
    failed = [case for case in cases if case.find("failure") is not None]
    assert [case.get("name") for case in failed] == ["test_discount_at_threshold"]
    assert "Decimal('100.00')" in ET.tostring(failed[0], encoding="unicode")
    patch = (output / "change.diff").read_text()
    assert '-    if subtotal >= Decimal("100.00"):' in patch
    assert '+    if subtotal > Decimal("100.00"):' in patch
    actual_diff = subprocess.run(["git", "diff", "--no-ext-diff", "--no-color", "HEAD", "--", "cart.py"],
                                 cwd=output / "project", text=True, capture_output=True, check=True)
    assert actual_diff.stdout == patch
    baseline_code = subprocess.run(["git", "show", "HEAD:cart.py"], cwd=output / "project",
                                   text=True, capture_output=True, check=True).stdout
    assert 'subtotal >= Decimal("100.00")' in baseline_code
    assert "1 failed, 4 passed" in (output / "stdout.log").read_text()
    persisted = json.loads((output / "metadata.json").read_text())
    assert metadata == persisted
    for path in ["metadata.json", "junit.xml", "baseline.xml", "stdout.log", "baseline.log", "change.diff"]:
        assert str(tmp_path) not in (output / path).read_text()
    assert all(not Path(path).is_absolute() for path in metadata["artifacts"].values())


def test_demo_preserves_existing_evidence(tmp_path):
    marker = tmp_path / "keep.txt"
    marker.write_text("existing evidence", encoding="utf-8")
    with pytest.raises(ValueError, match="must be empty"):
        load_demo().reproduce_demo(tmp_path)
    assert marker.read_text() == "existing evidence"
