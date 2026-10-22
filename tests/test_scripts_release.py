"""Regression checks for portable evaluation and export commands."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from opspilot.fault_lab import run_experiment


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script", ["download_chat_model.py", "download_embedding.py"])
def test_download_help_needs_no_optional_dependencies(script, tmp_path):
    result = subprocess.run([sys.executable, "-S", str(ROOT / "scripts" / script), "--help"],
                            cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert "--output-dir" in result.stdout and "--revision" in result.stdout


def test_live_eval_uses_configured_dataset_and_forwards_time_window(tmp_path, monkeypatch):
    script = load_script("eval_live")
    data = tmp_path / "custom_data"
    data.mkdir()
    bounds = {"start_time": "2026-10-20T09:00:00Z", "end_time": "2026-10-20T09:01:00Z"}
    (data / "eval.jsonl").write_text(json.dumps({"id": "scoped", "split": "test", "kind": "tool",
                                                  "question": "统计orders-api", **bounds}) + "\n", encoding="utf-8")
    output = tmp_path / "evaluation.json"
    calls = []

    class RecordingAgent:
        def ask(self, question, **kwargs):
            calls.append((question, kwargs))
            return {"mode": "llm", "status": "answered", "model_calls": 1}

    def build_agent(**kwargs):
        assert kwargs["data_dir"] == data
        return RecordingAgent()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPS_DATA_DIR", str(data))
    monkeypatch.setenv("OPS_MODE", "llm")
    monkeypatch.setattr(script, "build_agent", build_agent)
    monkeypatch.setattr(sys, "argv", ["eval_live.py", "--allow-api", "--output", str(output)])
    script.main()
    assert calls == [("统计orders-api", bounds)]
    assert json.loads(output.read_text())["cases"] == 1


@pytest.mark.parametrize("name", ["eval_live", "eval_local"])
def test_empty_model_evaluations_fail_before_loading_or_calling_a_model(name, tmp_path, monkeypatch):
    script = load_script(name)
    dataset = tmp_path / "empty.jsonl"
    dataset.write_text("\n", encoding="utf-8")
    monkeypatch.setenv("OPS_MODE", "llm")
    monkeypatch.setattr(script, "build_agent", lambda **kwargs: pytest.fail("empty data must not load a model"))
    argv = [f"{name}.py", "--dataset", str(dataset)]
    if name == "eval_live":
        argv.append("--allow-api")
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        script.main()
    assert exc.value.code == 2


def test_fault_summary_and_legacy_exports_do_not_include_user_paths(tmp_path, monkeypatch):
    summary = run_experiment(tmp_path / "raw", requests_per_scenario=1)
    source = Path(summary["artifacts"]["summary.json"])
    persisted = json.loads(source.read_text())
    assert all(not Path(path).is_absolute() for path in persisted["artifacts"].values())
    assert str(tmp_path) not in source.read_text()
    # Exporting an older run also strips its machine-specific artifact paths.
    source.write_text(json.dumps(summary), encoding="utf-8")
    output = tmp_path / "portable_report"
    script = load_script("verify_fault_integration")
    monkeypatch.setattr(sys, "argv", ["verify_fault_integration.py", "--summary", str(source),
                                      "--output", str(output), "--state-dir", str(tmp_path / "state")])
    script.main()
    exported = json.loads((output / "summary.json").read_text())
    manifest = json.loads((output / "integration.json").read_text())
    assert all((output / path).is_file() for path in exported["artifacts"].values())
    assert str(tmp_path) not in (output / "summary.json").read_text()
    assert manifest["statistics_exact_matches"] == manifest["cases"] == 5
    assert manifest["source_sha256"]["summary.json"] != manifest["exported_sha256"]["summary.json"]
