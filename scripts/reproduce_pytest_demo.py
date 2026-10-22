"""Produce a real pytest failure by deliberately changing a tiny cart rule.

Only the fixed, repository-owned example is executed. No command supplied by a
user or by a model is evaluated. The generated Git project remains available
for subsequent read-only triage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "pytest_demo"
BEFORE = 'if subtotal >= Decimal("100.00"):'
AFTER = 'if subtotal > Decimal("100.00"):'


def _run(argv: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True,
                          timeout=60, check=False)


def _portable(text: str, output: Path, project: Path) -> str:
    # pytest includes the report destination in its terminal summary. Retain the
    # evidence while removing the machine-specific output directory from exports.
    for source, replacement in ((str(project), "<demo-project>"),
                                (str(output), "<demo-output>")):
        text = text.replace(source, replacement)
        text = text.replace(source.replace("\\", "/"), replacement)
    return text


def _test_counts(report: Path) -> dict[str, int]:
    cases = ET.parse(report).getroot().findall(".//testcase")
    return {"tests": len(cases),
            "failures": sum(case.find("failure") is not None for case in cases),
            "errors": sum(case.find("error") is not None for case in cases),
            "skipped": sum(case.find("skipped") is not None for case in cases)}


def reproduce_demo(output_dir: Path) -> dict:
    """Create a new demo project and verify the expected pass/fail transition."""
    output = output_dir.expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("output directory must be empty; choose a new --output-dir")
    if not shutil.which("git"):
        raise RuntimeError("Git is required to create the demonstration repository")
    if not EXAMPLE.is_dir():
        raise RuntimeError("run this source-checkout script with examples/pytest_demo available")
    output.mkdir(parents=True, exist_ok=True)
    project = output / "project"
    shutil.copytree(EXAMPLE, project,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
    env = os.environ.copy()
    # External plugins/configuration must not change this fixed demonstration.
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    env.pop("PYTHONPATH", None)
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull

    def git(*args: str) -> str:
        process = _run(["git", "-c", f"core.hooksPath={os.devnull}",
                        "-c", "core.fsmonitor=false", *args], project, env)
        if process.returncode:
            raise RuntimeError("demonstration Git setup failed: " +
                               _portable(process.stderr.strip(), output, project))
        return process.stdout

    git("init", "--initial-branch=main", "--quiet")
    git("add", ".")
    git("-c", "user.name=OpsPilot Demo", "-c", "user.email=demo@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Passing cart example baseline")

    def run_pytest(report_name: str, log_name: str) -> dict:
        report = output / report_name
        process = _run([sys.executable, "-m", "pytest", "-q", "--tb=short", "-c", "pytest.ini",
                        f"--junitxml=../{report_name}"], project, env)
        (output / log_name).write_text(
            _portable(process.stdout + process.stderr, output, project), encoding="utf-8")
        if not report.is_file():
            raise RuntimeError(f"pytest did not generate {report_name}; inspect {log_name}")
        report.write_text(_portable(report.read_text(encoding="utf-8"), output, project),
                          encoding="utf-8")
        return {"exit_code": process.returncode, **_test_counts(report)}

    baseline = run_pytest("baseline.xml", "baseline.log")
    if baseline != {"exit_code": 0, "tests": 5, "failures": 0, "errors": 0, "skipped": 0}:
        raise RuntimeError("baseline did not pass all five tests; inspect baseline.log")
    source = project / "cart.py"
    code = source.read_text(encoding="utf-8")
    if code.count(BEFORE) != 1:
        raise RuntimeError("expected discount boundary was not found exactly once")
    source.write_text(code.replace(BEFORE, AFTER, 1), encoding="utf-8")
    regression = run_pytest("junit.xml", "stdout.log")
    if regression != {"exit_code": 1, "tests": 5, "failures": 1, "errors": 0, "skipped": 0}:
        raise RuntimeError("expected exactly one assertion failure; inspect stdout.log")
    failures = ET.parse(output / "junit.xml").getroot().findall(".//testcase[failure]")
    if len(failures) != 1 or failures[0].get("name") != "test_discount_at_threshold":
        raise RuntimeError("the expected threshold test did not fail")
    diff = git("diff", "--no-ext-diff", "--no-color", "HEAD", "--", "cart.py")
    (output / "change.diff").write_text(diff, encoding="utf-8")
    artifacts = {"repository": "project", "baseline_junit": "baseline.xml",
                 "baseline_log": "baseline.log", "failure_junit": "junit.xml",
                 "failure_log": "stdout.log", "diff": "change.diff",
                 "rules": "project/docs/cart-rules.md"}
    metadata = {
        "scenario": "cart-inclusive-discount-boundary",
        "data_kind": "deliberately_introduced_regression",
        "description": "A fixed demonstration changes >= to > for the inclusive 100.00 discount.",
        "baseline": baseline,
        "regression": regression,
        "failed_test": "test_cart.py::test_discount_at_threshold",
        "baseline_commit": git("rev-parse", "HEAD").strip(),
        "pytest_command": ["python", "-m", "pytest", "-q", "--tb=short", "-c", "pytest.ini",
                           "--junitxml=../junit.xml"],
        "artifacts": artifacts,
        "sha256": {name: hashlib.sha256((output / path).read_bytes()).hexdigest()
                   for name, path in artifacts.items() if name != "repository"},
    }
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("var/pytest_demo"),
                        help="new or empty output directory (default: var/pytest_demo)")
    args = parser.parse_args()
    try:
        metadata = reproduce_demo(args.output_dir)
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired, ET.ParseError) as exc:
        parser.exit(1, f"Demo generation failed: {exc}\n")
    print(json.dumps({"data_kind": metadata["data_kind"], "baseline": metadata["baseline"],
                      "regression": metadata["regression"], "artifacts": metadata["artifacts"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
