"""Real Git regressions for the analyzer's read-only source boundary."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from xml.sax.saxutils import escape

from opspilot.triage import analyze_failure


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "test_app.py").write_text("def test_value():\n    assert False\n")
    (root / "app.py").write_text("BASE = 1\n")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base")
    return root


def report(tmp_path: Path, trace: str = "test_app.py:2: AssertionError") -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(
        '<testsuite><testcase classname="test_app" name="test_value">'
        f"<failure>{escape(trace)}</failure></testcase></testsuite>"
    )
    return path


def test_core_worktree_cannot_read_sources_outside_selected_root(tmp_path):
    root = repository(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "app.py").write_text("EXTERNAL_FILE_MARKER = 2\n")
    (outside / "test_app.py").write_text("def test_value():\n    assert False\n")
    (root / "app.py").write_text("SELECTED_ROOT_CHANGE = 3\n")
    git(root, "config", "core.worktree", str(outside))

    result = analyze_failure(root, report(tmp_path), base_ref="HEAD")

    serialized = json.dumps(result)
    assert "EXTERNAL_FILE_MARKER" not in serialized
    assert "SELECTED_ROOT_CHANGE" in serialized
    assert result["diff_match"]["status"] == "no_match"
    assert result["diff_match"]["paths"] == ["app.py"]


def test_parent_repository_is_not_discovered_for_project_subdirectory(tmp_path):
    root = repository(tmp_path)
    nested = root / "nested"
    nested.mkdir()
    (nested / "test_app.py").write_text("def test_value():\n    assert False\n")
    git(root, "add", "nested")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "nested")
    (nested / "test_app.py").write_text("def test_value():\n    assert 1 == 2\n")

    result = analyze_failure(nested, report(tmp_path), base_ref="HEAD")

    assert result["status"] == "analysis_ready"
    assert result["diff_match"]["status"] == "unavailable"
    assert not any(item["kind"] == "git_diff" for item in result["evidence"])
    assert any("Git evidence unavailable" in warning for warning in result["warnings"])


def test_linked_worktree_gitfile_remains_supported(tmp_path):
    root = repository(tmp_path)
    linked = tmp_path / "linked"
    git(root, "worktree", "add", "--detach", str(linked), "HEAD")
    assert (linked / ".git").is_file()
    (linked / "app.py").write_text("LINKED_WORKTREE_CHANGE = 2\n")

    result = analyze_failure(linked, report(tmp_path), base_ref="HEAD")

    assert result["diff_match"]["paths"] == ["app.py"]
    assert "LINKED_WORKTREE_CHANGE" in json.dumps(result)
    assert result["diff_match"]["status"] == "no_match"


def test_git_presentation_config_does_not_change_patch_parsing(tmp_path):
    root = repository(tmp_path)
    for key, value in (
        ("color.ui", "always"), ("diff.noprefix", "true"),
        ("diff.mnemonicPrefix", "true"), ("diff.relative", "true"),
        ("diff.outputIndicatorNew", ">"), ("diff.outputIndicatorOld", "<"),
        ("diff.outputIndicatorContext", "."),
    ):
        git(root, "config", key, value)
    (root / "test_app.py").write_text("def test_value():\n    assert 1 == 2\n")

    result = analyze_failure(root, report(tmp_path), base_ref="HEAD")

    assert result["diff_match"]["status"] == "matched"
    assert result["diff_match"]["locations"] == [{"path": "test_app.py", "line": 2}]
    patches = [item["text"] for item in result["evidence"] if item["kind"] == "git_diff"]
    assert any("+    assert 1 == 2" in patch for patch in patches)
    assert all("\x1b" not in patch for patch in patches)


def test_paths_with_git_pathspec_magic_are_literal(tmp_path):
    root = repository(tmp_path)
    name = ":(glob)target.py"
    (root / name).write_text("BASE = 1\n")
    git(root, "--literal-pathspecs", "add", name)
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "literal path")
    (root / name).write_text("LITERAL_PATH_CHANGE = 2\n")

    result = analyze_failure(root, report(tmp_path), base_ref="HEAD")

    assert any(item["kind"] == "git_diff" and item["path"] == name for item in result["evidence"])
    assert "LITERAL_PATH_CHANGE" in json.dumps(result)


def test_unicode_source_paths_are_not_escaped_out_of_patch_matching(tmp_path):
    root = repository(tmp_path)
    name = "计算.py"
    (root / name).write_text("BASE = 1\n")
    git(root, "add", name)
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "unicode path")
    (root / name).write_text("UNICODE_PATH_CHANGE = 2\n")

    result = analyze_failure(root, report(tmp_path), base_ref="HEAD")

    assert any(item["kind"] == "git_diff" and item["path"] == name for item in result["evidence"])
    assert "UNICODE_PATH_CHANGE" in json.dumps(result)


def test_external_diff_textconv_and_fsmonitor_helpers_are_not_executed(tmp_path):
    root = repository(tmp_path)
    marker = tmp_path / "helper-executed"
    helper = tmp_path / "helper.sh"
    helper.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    helper.chmod(0o755)
    git(root, "config", "diff.external", str(helper))
    git(root, "config", "diff.dangerous.textconv", str(helper))
    git(root, "config", "core.fsmonitor", str(helper))
    (root / ".gitattributes").write_text("*.py diff=dangerous\n")
    (root / "app.py").write_text("SAFE_DIFF_CHANGE = 2\n")

    result = analyze_failure(root, report(tmp_path), base_ref="HEAD")

    assert not marker.exists()
    assert "SAFE_DIFF_CHANGE" in json.dumps(result)


def test_symlink_git_directory_is_not_accepted_as_selected_repository(tmp_path):
    root = repository(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / "test_app.py").write_text("def test_value():\n    assert False\n")
    (other / ".git").symlink_to(root / ".git", target_is_directory=True)

    result = analyze_failure(other, report(tmp_path), base_ref="HEAD")

    assert result["diff_match"]["status"] == "unavailable"
    assert not any(item["kind"] == "git_diff" for item in result["evidence"])
