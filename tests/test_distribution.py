"""Distribution defaults work without a source checkout or writable package."""
from pathlib import Path

import pytest

from opspilot.cli import main
from opspilot.config import build_agent
from opspilot.evaluate import evaluate, retrieval_metrics
from opspilot.paths import bundled_data_dir, resolve_data_dir, resolve_state_dir
from opspilot.retrieval import Retriever, ingest


def test_packaged_examples_match_source():
    source = Path(__file__).resolve().parents[1] / "data"
    bundled = bundled_data_dir()
    files = sorted(path.relative_to(source) for path in source.rglob("*") if path.is_file())
    assert files
    assert files == sorted(path.relative_to(bundled) for path in bundled.rglob("*") if path.is_file())
    assert all((source / path).read_bytes() == (bundled / path).read_bytes() for path in files)


def test_data_selection_respects_explicit_and_environment_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPS_DATA_DIR", raising=False)
    assert resolve_data_dir() == bundled_data_dir()
    (tmp_path / "data" / "knowledge").mkdir(parents=True)
    assert resolve_data_dir() == tmp_path / "data"
    configured = tmp_path / "custom"
    monkeypatch.setenv("OPS_DATA_DIR", str(configured))
    assert resolve_data_dir() == configured
    explicit = tmp_path / "explicit"
    assert resolve_data_dir(explicit) == explicit
    with pytest.raises(ValueError, match="No Markdown knowledge"):
        build_agent(state_dir=tmp_path / "state", offline=True)


def test_state_paths_are_separate_from_package_resources(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPS_STATE_DIR", raising=False)
    assert resolve_state_dir() == Path("var")
    assert resolve_state_dir().resolve() == tmp_path / "var"
    monkeypatch.setenv("OPS_STATE_DIR", str(tmp_path / "state"))
    assert resolve_state_dir() == tmp_path / "state"
    assert resolve_state_dir(tmp_path / "explicit") == tmp_path / "explicit"


def test_agent_and_eval_from_an_unrelated_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPS_DATA_DIR", raising=False)
    monkeypatch.delenv("OPS_STATE_DIR", raising=False)
    monkeypatch.delenv("OPS_EMBED_MODEL", raising=False)
    monkeypatch.setenv("OPS_RETRIEVER", "bm25")
    result = build_agent(offline=True).ask("统计orders-api日志错误率")
    assert result["status"] == "answered"
    assert result["log_stats"]["requests"] == 100
    assert (tmp_path / "var" / "runs.sqlite3").is_file()
    report = evaluate(output=tmp_path / "reports")
    assert report["cases"] > 0
    assert report["agent"]["tool_exact_matches"] == report["agent"]["tool_cases"]
    assert (tmp_path / "reports" / "test_results.json").is_file()


def test_ingest_cli_defaults_to_packaged_data_and_custom_state(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPS_DATA_DIR", raising=False)
    monkeypatch.setenv("OPS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr("sys.argv", ["opspilot", "ingest"])
    main()
    assert (tmp_path / "state" / "index.json").is_file()
    assert "Indexed" in capsys.readouterr().out


def test_ingest_cli_rejects_empty_directory(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["opspilot", "ingest", "--directory", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


@pytest.mark.parametrize("value", [0, -1, 1.5, "5", True, None])
def test_search_rejects_invalid_k(value):
    with pytest.raises(ValueError, match="positive integer"):
        Retriever([]).search("query", value)
    with pytest.raises(ValueError, match="positive integer"):
        retrieval_metrics(["a"], ["a"], value)


@pytest.mark.parametrize("value", [0, -1, 1.5, "5", True, None])
def test_ingest_rejects_invalid_chunk_size(tmp_path, value):
    with pytest.raises(ValueError, match="max_chars"):
        ingest(tmp_path, max_chars=value)


@pytest.mark.parametrize("value", [-1, 1.5, "1", True, None])
def test_ingest_rejects_invalid_overlap(tmp_path, value):
    with pytest.raises(ValueError, match="overlap_lines"):
        ingest(tmp_path, overlap_lines=value)


def test_evaluation_rejects_invalid_split(tmp_path):
    with pytest.raises(ValueError, match="split"):
        evaluate(split="missing", output=tmp_path)


def test_retrieval_metrics_require_relevant_documents():
    with pytest.raises(ValueError, match="relevant"):
        retrieval_metrics(["a"], [])
