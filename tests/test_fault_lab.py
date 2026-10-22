import csv
import json
from datetime import datetime, timezone

import httpx
import pytest

from opspilot.fault_lab import CsvRecorder, LocalFaultServer, SCENARIOS, run_experiment


def test_real_loopback_fault_experiment(tmp_path):
    before = datetime.now(timezone.utc)
    summary = run_experiment(tmp_path, requests_per_scenario=2)
    after = datetime.now(timezone.utc)
    with open(summary["artifacts"]["logs.csv"], encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    observations = json.loads(open(summary["artifacts"]["client_observations.json"], encoding="utf-8").read())
    assert len(rows) == summary["server_requests"] == summary["client_requests"] == 10
    assert {row["scenario"] for row in rows} == set(SCENARIOS)
    assert len({row["request_id"] for row in rows}) == 10
    assert {row["request_id"] for row in rows} == {row["request_id"] for row in observations}
    assert all(row["service"] == "orders-api" and row["data_kind"] == "local_fault_injection" for row in rows)
    assert all(before <= datetime.fromisoformat(row["timestamp"]) <= after for row in rows)
    by_scenario = {row["scenario"]: row for row in summary["scenarios"]}
    assert by_scenario["rate_limit"]["status_counts"] == {"429": 2}
    assert by_scenario["unavailable"]["status_counts"] == {"503": 2}
    assert by_scenario["slow"]["p95_ms"] >= 45
    assert by_scenario["timeout"]["p95_ms"] >= 75
    assert by_scenario["timeout"]["status_counts"] == {"200": 2}
    assert by_scenario["timeout"]["client_timeout_count"] == 2
    assert all(row["transport_error_count"] == 0 for row in summary["scenarios"])
    for window in summary["scenarios"]:
        subset = [row for row in rows if window["start_time"] <= row["timestamp"] <= window["end_time"]]
        assert len(subset) == 2
        assert {row["scenario"] for row in subset} == {window["scenario"]}
    timed_out = [row for row in observations if row["scenario"] == "timeout"]
    assert all(row["outcome"] == "client_timeout" and row["status"] is None for row in timed_out)
    # Cleanup is observable: the completed experiment no longer accepts requests.
    with httpx.Client(trust_env=False, timeout=0.2) as client, pytest.raises(httpx.ConnectError):
        client.get(summary["base_url"] + "/health")


def test_unknown_fault_header_rejected_over_real_http(tmp_path):
    recorder = CsvRecorder(tmp_path / "logs.csv", "test-rejection")
    with LocalFaultServer(recorder) as server, httpx.Client(trust_env=False) as client:
        response = client.get(server.base_url + "/orders", headers={"X-Lab-Scenario": "shell"})
        assert response.status_code == 400
        recorder.wait_for_count(1)
    assert recorder.snapshot()[0]["scenario"] == "rejected"
    assert recorder.snapshot()[0]["status"] == 400


def test_experiment_preserves_previous_logs(tmp_path):
    path = tmp_path / "existing.csv"
    path.write_text("previous evidence\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        CsvRecorder(path, "must-not-overwrite")
    assert path.read_text(encoding="utf-8") == "previous evidence\n"
    with pytest.raises(ValueError):
        run_experiment(tmp_path, requests_per_scenario=0)
