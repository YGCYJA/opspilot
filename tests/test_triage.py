from __future__ import annotations

import json
from pathlib import Path
import subprocess
from xml.sax.saxutils import escape, quoteattr

import pytest

from opspilot.triage import analyze_failure, render_report


def report(tmp_path: Path, cases: str, name: str = "junit.xml") -> Path:
    path = tmp_path / name
    path.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>", encoding="utf-8")
    return path


def failure_case(text="test_app.py:4: AssertionError\nE   AssertionError: expected 2, received 1", *, name="test_value", classname="test_app", kind="failure"):
    return f'<testcase classname={quoteattr(classname)} name={quoteattr(name)}><{kind} message="unexpected value">{escape(text)}</{kind}></testcase>'


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "test_app.py").write_text("from app import value\n\ndef test_value():\n    assert value() == 2\n", encoding="utf-8")
    (root / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    return root


def git(root: Path, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def init_git(root: Path):
    git(root, "init", "-q")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "add", ".")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "baseline")


def test_counts_are_derived_from_test_cases_not_untrusted_suite_totals(tmp_path, project):
    xml = report(tmp_path, '<testcase name="a"/><testcase name="b"><skipped/></testcase>')
    result = analyze_failure(project, xml)
    assert result["status"] == "no_failures"
    assert result["summary"] == dict(tests=2, passed=1, failures=0, errors=0, skipped=1)
    assert result["reproduction"] is None


def test_first_real_failure_is_selected_in_document_order(tmp_path, project):
    xml = report(tmp_path, '<testcase name="skip"><skipped/></testcase>' + failure_case() + failure_case(name="test_other", kind="error"))
    first = analyze_failure(project, xml)
    second = analyze_failure(project, xml)
    assert first["status"] == "analysis_ready"
    assert first["summary"] == dict(tests=3, passed=0, failures=1, errors=1, skipped=1)
    assert first["first_failure"]["nodeid"] == "test_app.py::test_value"
    assert first["first_failure"]["locations"] == [{"path": "test_app.py", "line": 4}]
    assert first["first_failure"]["exception"].startswith("AssertionError")
    assert first["evidence"] == second["evidence"]
    assert any(item["kind"] == "source_context" for item in first["evidence"])
    assert first["reproduction"]["argv"] == ["python", "-m", "pytest", "test_app.py::test_value", "-q"]
    assert first["reproduction"]["executed"] is False
    assert "Hypotheses" in render_report(first)


def test_collection_error_is_not_reported_as_test_assertion(tmp_path, project):
    xml = report(tmp_path, failure_case("E   ModuleNotFoundError: No module named 'optional_dependency'", name="test_app.py", classname="", kind="error"))
    result = analyze_failure(project, xml)
    assert result["summary"]["errors"] == 1
    assert result["first_failure"]["kind"] == "error"
    assert result["first_failure"]["nodeid"] == "test_app.py"
    assert result["first_failure"]["exception"].startswith("ModuleNotFoundError")


@pytest.mark.parametrize("value", ["<bad", "<other/>", "<testsuite/>", '<!DOCTYPE testsuite [<!ENTITY x "secret">]><testsuite/>'])
def test_bad_or_empty_xml_is_safe_invalid_input(tmp_path, project, value):
    xml = tmp_path / "bad.xml"
    xml.write_text(value)
    result = analyze_failure(project, xml)
    assert result["status"] == "invalid_input"
    assert result["warnings"]
    assert result["evidence"] == []


def test_utf16_entity_declaration_is_rejected_before_parsing(tmp_path, project):
    xml = tmp_path / "utf16.xml"
    xml.write_bytes('<!DOCTYPE testsuite [<!ENTITY x "secret">]><testsuite/>'.encode("utf-16"))
    assert "DTD" in analyze_failure(project, xml)["warnings"][0]


def test_large_xml_is_bounded(tmp_path, project):
    xml = tmp_path / "huge.xml"
    xml.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    assert analyze_failure(project, xml)["status"] == "invalid_input"


def test_external_traceback_path_is_not_read(tmp_path, project):
    outside = tmp_path / "private.py"
    outside.write_text("DO_NOT_READ_THIS")
    xml = report(tmp_path, failure_case(f"{outside}:1: RuntimeError\n../private.py:1: RuntimeError"))
    result = analyze_failure(project, xml)
    assert result["first_failure"]["locations"] == []
    assert not any(item["kind"] == "source_context" for item in result["evidence"])
    assert "DO_NOT_READ_THIS" not in json.dumps(result)


def test_symlink_source_and_notes_are_not_followed(tmp_path, project):
    outside = tmp_path / "secret.py"
    outside.write_text("DO_NOT_READ_THIS")
    (project / "linked.py").symlink_to(outside)
    outside_docs = tmp_path / "outside-docs"
    outside_docs.mkdir()
    (outside_docs / "rule.md").write_text("DO_NOT_READ_THIS")
    (project / "notes").symlink_to(outside_docs, target_is_directory=True)
    xml = report(tmp_path, failure_case("linked.py:1: RuntimeError"))
    result = analyze_failure(project, xml, notes_dir=project / "notes")
    assert result["first_failure"]["locations"] == []
    assert "DO_NOT_READ_THIS" not in json.dumps(result)
    assert "Notes must" in " ".join(result["warnings"])


def test_symlink_junit_is_rejected(tmp_path, project):
    xml = report(tmp_path, failure_case())
    link = tmp_path / "link.xml"
    link.symlink_to(xml)
    assert analyze_failure(project, link)["status"] == "invalid_input"


def test_parent_directory_alias_is_allowed_but_repo_internal_links_are_not(tmp_path, project):
    docs = project / "docs"
    docs.mkdir()
    (docs / "rules.md").write_text("The value function must return 2 for test_value.\n")
    xml = report(tmp_path, failure_case())
    alias = tmp_path / "parent-alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    result = analyze_failure(alias / "project", alias / xml.name, notes_dir=alias / "project" / "docs")
    assert result["status"] == "analysis_ready"
    assert any(item["kind"] == "project_note" for item in result["evidence"])
    (project / "docs-link").symlink_to(docs, target_is_directory=True)
    (project / "source-link").symlink_to(project, target_is_directory=True)
    xml = report(tmp_path, failure_case("source-link/app.py:1: AssertionError"))
    result = analyze_failure(project, xml, notes_dir=project / "docs-link")
    assert result["first_failure"]["locations"] == []
    assert not any(item["kind"] == "project_note" for item in result["evidence"])


def test_git_changed_line_match_and_command_is_never_run(tmp_path, project):
    init_git(project)
    (project / "test_app.py").write_text("from app import value\n\ndef test_value():\n    assert value() == 100\n")
    xml = report(tmp_path, failure_case())
    before = git(project, "status", "--porcelain")
    result = analyze_failure(project, xml, base_ref="HEAD")
    assert result["diff_match"]["status"] == "matched"
    assert result["diff_match"]["locations"] == [{"path": "test_app.py", "line": 4}]
    assert any(item["kind"] == "git_diff" for item in result["evidence"])
    assert git(project, "status", "--porcelain") == before
    assert result["reproduction"]["executed"] is False


def test_one_hop_import_call_is_related_but_not_a_traceback_match(tmp_path, project):
    docs = project / "docs"
    docs.mkdir()
    (docs / "rules.md").write_text("# value\nThe value() function must return 2 for test_value.\n")
    init_git(project)
    (project / "app.py").write_text("def value():\n    return 1\n")
    xml = report(tmp_path, failure_case())
    result = analyze_failure(project, xml, base_ref="HEAD", notes_dir=docs)
    assert result["diff_match"]["status"] == "no_match"
    related = result["related_changes"][0]
    assert related["path"] == "app.py"
    assert related["symbol"] == "value"
    assert related["relationship"] == "imported_by_failed_test"
    assert any(item["kind"] == "project_note" for item in result["evidence"])
    assert all(item["status"] == "unverified" for item in result["hypotheses"])
    ids = {item["id"] for item in result["evidence"]}
    assert set(related["evidence_ids"]) <= ids


@pytest.mark.parametrize("budget", ["directories", "depth"])
def test_note_directory_scan_is_bounded_and_reports_truncation(tmp_path, project, monkeypatch, budget):
    import opspilot.triage as triage
    docs = project / "docs"
    docs.mkdir()
    if budget == "directories":
        monkeypatch.setattr(triage, "MAX_NOTE_DIRECTORIES", 2)
        for name in ("a", "b", "c"):
            folder = docs / name
            folder.mkdir()
            (folder / "rule.md").write_text("value test_value must return 2")
    else:
        monkeypatch.setattr(triage, "MAX_NOTE_DEPTH", 1)
        nested = docs / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "rule.md").write_text("DEEP_NOTE_MUST_NOT_BE_READ")
    result = analyze_failure(project, report(tmp_path, failure_case()), notes_dir=docs)
    assert "scan was bounded" in " ".join(result["warnings"])
    if budget == "depth":
        assert "DEEP_NOTE_MUST_NOT_BE_READ" not in json.dumps(result)


def test_same_name_function_without_import_call_does_not_create_association(tmp_path, project):
    init_git(project)
    (project / "unrelated.py").write_text("def value():\n    return 1\n")
    git(project, "add", "unrelated.py")
    # app.py is untouched and unrelated.py is not imported by the test.
    result = analyze_failure(project, report(tmp_path, failure_case()), base_ref="HEAD")
    assert result["related_changes"] == []
    assert result["diff_match"]["status"] == "no_match"


@pytest.mark.parametrize("source", [
    "from app import value\n\ndef test_value():\n    value = lambda: 7\n    assert value() == 2\n",
    "from app import value\n\ndef test_value(value):\n    assert value() == 2\n",
    "from app import value\n\ndef test_value():\n    from other import value\n    assert value() == 2\n",
])
def test_locally_shadowed_import_does_not_create_association(tmp_path, project, source):
    (project / "test_app.py").write_text(source)
    init_git(project)
    (project / "app.py").write_text("def value():\n    return 1\n")
    result = analyze_failure(project, report(tmp_path, failure_case()), base_ref="HEAD")
    assert result["related_changes"] == []


def test_sensitive_changed_files_are_excluded(tmp_path, project):
    (project / ".env").write_text("API_KEY=DO_NOT_PUBLISH")
    init_git(project)
    (project / ".env").write_text("API_KEY=ALSO_DO_NOT_PUBLISH")
    result = analyze_failure(project, report(tmp_path, failure_case()), base_ref="HEAD")
    assert not any(item["path"] == ".env" for item in result["evidence"])
    assert "DO_NOT_PUBLISH" not in json.dumps(result)


@pytest.mark.parametrize("ref", ["--output=/tmp/something", "HEAD\n--bad", "missing-branch"])
def test_invalid_base_ref_is_safe_unavailable(tmp_path, project, ref):
    init_git(project)
    result = analyze_failure(project, report(tmp_path, failure_case()), base_ref=ref)
    assert result["status"] == "analysis_ready"
    assert result["diff_match"]["status"] == "unavailable"
    assert result["warnings"]


def test_credential_and_ansi_redaction(tmp_path, project):
    trace = "test_app.py:4: AssertionError\n\x1b[31mAssertionError\x1b[0m: password=secretvalue Authorization: Bearer abcdefghijkl sk-123456789abcd"
    result = analyze_failure(project, report(tmp_path, failure_case(trace)))
    serialized = json.dumps(result)
    assert "secretvalue" not in serialized
    assert "abcdefghijkl" not in serialized
    assert "sk-123456789abcd" not in serialized
    assert "\\u001b" not in serialized


class FakeModel:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def complete(self, messages, json_mode=False):
        self.calls += 1
        return self.response(messages) if callable(self.response) else self.response


@pytest.mark.parametrize("response", [None, [], {"content": 123}, {"content": "{bad"}, {"content": "[]"},
    {"content": '{"claims": [{"claim":"The database is broken", "source_id":"invented", "quote":"imaginary database logs"}]}'},
    {"content": '{"claims": [null]}'}, {"content": '{"claims": []}'}])
def test_model_schema_or_citation_failure_preserves_offline_report(tmp_path, project, response):
    result = analyze_failure(project, report(tmp_path, failure_case()), model_factory=lambda: FakeModel(response))
    assert result["status"] == "analysis_ready"
    assert result["model"]["status"] == "offline_fallback"
    assert not any(item["origin"] == "model" for item in result["hypotheses"])
    assert result["evidence"]


def test_model_accepted_only_with_exact_quote_and_still_unverified(tmp_path, project):
    def response(messages):
        source = json.loads(messages[-1]["content"])["evidence"][0]
        return {"content": json.dumps({"claims": [{"claim": "Check the failing assertion.", "source_id": source["id"], "quote": source["text"][:30]}]})}
    result = analyze_failure(project, report(tmp_path, failure_case()), model_factory=lambda: FakeModel(response))
    assert result["model"] == {"mode": "model", "backend": "custom", "status": "validated_citations", "calls": 1}
    model_claim = next(item for item in result["hypotheses"] if item["origin"] == "model")
    assert model_claim["status"] == "unverified"


def test_provider_exception_is_not_leaked(tmp_path, project):
    def factory():
        raise RuntimeError("password=provider-secret")
    result = analyze_failure(project, report(tmp_path, failure_case()), model_factory=factory)
    assert result["model"]["calls"] == 0
    assert result["model"]["status"] == "offline_fallback"
    assert "provider-secret" not in json.dumps(result)


def test_model_retry_count_and_bare_api_key_echo_are_recorded_safely(tmp_path, project):
    class RetryingModel:
        calls = 0
        api_key = "bare-provider-credential"

        def complete(self, messages, json_mode=False):
            self.calls += 2
            source = json.loads(messages[-1]["content"])["evidence"][0]
            return {"content": json.dumps({"claims": [{"claim": "Check this result: bare-provider-credential", "source_id": source["id"], "quote": source["text"][:30]}]})}

    result = analyze_failure(project, report(tmp_path, failure_case()), model_factory=RetryingModel)
    assert result["model"]["calls"] == 2
    assert "bare-provider-credential" not in json.dumps(result)
    assert "[REDACTED]" in json.dumps(result)


def test_render_fences_cannot_be_closed_by_traceback(tmp_path, project):
    result = analyze_failure(project, report(tmp_path, failure_case("```\n![image](https://invalid.example/image)\n```\nAssertionError: failure")))
    rendered = render_report(result)
    assert "````text" in rendered
    assert len(rendered) < 100_000


def test_format_placeholder_is_not_accepted_as_a_model_explanation(tmp_path, project):
    def response(messages):
        source = json.loads(messages[-1]['content'])['evidence'][0]
        return {'content': json.dumps({'claims': [{'claim': 'A tentative explanation to verify', 'source_id': source['id'], 'quote': source['text'][:30]}]})}
    result = analyze_failure(project, report(tmp_path, failure_case()), model_factory=lambda: FakeModel(response))
    assert result['model']['status'] == 'offline_fallback'
    assert not any(item['origin'] == 'model' for item in result['hypotheses'])


def test_report_retains_exact_input_hash_and_chosen_git_baseline(tmp_path, project):
    import hashlib
    init_git(project)
    xml = report(tmp_path, failure_case())
    result = analyze_failure(project, xml, base_ref='HEAD')
    assert result['report_sha256'] == hashlib.sha256(xml.read_bytes()).hexdigest()
    assert result['diff_match']['base_ref'] == 'HEAD'
    assert result['diff_match']['base_commit'] == git(project, 'rev-parse', 'HEAD').strip()
