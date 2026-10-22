import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opspilot.api import create_app
from opspilot.cli import main
from opspilot.models import model_factory_from_env
from opspilot.privacy import redact, redact_value


@pytest.fixture
def inputs(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'test_demo.py').write_text('def test_total():\n    assert 100 == 90\n')
    report = tmp_path / 'junit.xml'
    report.write_text('<testsuites><testsuite><testcase classname="test_demo" name="test_total"><failure message="assert 100 == 90">test_demo.py:2: AssertionError</failure></testcase></testsuite></testsuites>')
    return project, report


def test_cli_report_can_be_opened_and_invalid_input_has_distinct_exit(inputs, tmp_path, monkeypatch, capsys):
    project, report = inputs
    output = tmp_path / 'report'
    monkeypatch.setattr('sys.argv', ['opspilot', 'triage', '--repo', str(project), '--junit', str(report), '--output', str(output), '--offline', '--json'])
    main()
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'analysis_ready'
    assert json.loads((output / 'report.json').read_text()) == result
    assert 'test_demo.py::test_total' in (output / 'report.md').read_text()
    monkeypatch.setattr('sys.argv', ['opspilot', 'triage', '--repo', str(project), '--junit', str(tmp_path / 'absent.xml'), '--offline'])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_api_and_home_page_are_usable(inputs, monkeypatch):
    monkeypatch.setenv('OPS_MODE', 'offline')
    project, report = inputs
    with TestClient(create_app()) as client:
        assert client.get('/').status_code == 200
        assert 'pytest' in client.get('/').text
        assert client.get('/health').json()['version'] == '0.2.0'
        result = client.post('/triage', json={'repo': str(project), 'junit': str(report), 'offline': True})
        assert result.status_code == 200
        assert result.json()['first_failure']['nodeid'] == 'test_demo.py::test_total'
        assert client.post('/triage', json={'repo': str(project), 'junit': str(report.with_name('absent.xml'))}).status_code == 422
        # Obsolete incident routes no longer define this application's scope.
        assert client.post('/ask', json={'question': 'hello'}).status_code == 404


def test_bad_model_settings_do_not_prevent_offline_api_analysis(inputs, monkeypatch):
    monkeypatch.setenv('OPS_MODE', 'unknown')
    project, report = inputs
    with TestClient(create_app()) as client:
        payload = {'repo': str(project), 'junit': str(report)}
        assert client.post('/triage', json=payload).status_code == 422
        assert client.post('/triage', json={**payload, 'offline': True}).json()['status'] == 'analysis_ready'
        rejected = client.post('/triage', json={'repo': 'secret-key\n', 'junit': str(report)})
        assert rejected.status_code == 422 and 'secret-key' not in rejected.text


def test_offline_flag_prevents_accidental_provider_configuration(monkeypatch):
    monkeypatch.setenv('OPS_MODE', 'llm')
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    assert model_factory_from_env(force_offline=True) is None
    with pytest.raises(ValueError, match='requires'):
        model_factory_from_env()


@pytest.mark.parametrize('secret', [
    'Authorization: Basic dGVzdDpwYXNz',
    'password="abc def ghi"',
    "'api_key': 'abc def ghi'",
    'AWS_SECRET_ACCESS_KEY=example-secret-value',
    '-----BEGIN ' + 'PRIVATE KEY-----\nprivate bytes\n-----END ' + 'PRIVATE KEY-----',
])
def test_export_redacts_supported_credential_patterns(secret):
    clean = redact(secret)
    for token in ['dGVzdDpwYXNz', 'abc def ghi', 'example-secret-value', 'private bytes']:
        assert token not in clean
    assert 'REDACTED' in clean
    assert redact_value({'value': 'configured-value'}, ('configured-value',)) == {'value': '[REDACTED]'}
