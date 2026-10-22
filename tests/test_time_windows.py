import csv
from pathlib import Path

import pytest

from opspilot.retrieval import Retriever
from opspilot.tools import TOOL_SPECS, LogArgs, ToolRegistry


def registry(tmp_path: Path, rows: list[dict], *, provenance: bool = False) -> ToolRegistry:
    path = tmp_path / "logs.csv"
    fields = ["timestamp", "service", "status", "latency_ms", "request_id"]
    if provenance:
        fields.append("data_kind")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return ToolRegistry(Retriever([]), path)


@pytest.fixture
def sample_rows():
    return [
        {"timestamp": timestamp, "service": "orders-api", "status": status,
         "latency_ms": latency, "request_id": f"request-{i}"}
        for i, (timestamp, status, latency) in enumerate([
            ("2026-10-20T09:00:00Z", 200, 10),
            ("2026-10-20T17:00:01+08:00", 400, 20),
            ("2026-10-20T04:00:02-05:00", 500, 30),
            ("2026-10-20T09:00:03Z", 200, 40),
        ])
    ]


def analyze(tool, **bounds):
    return tool.execute("analyze_service_logs", {"service": "orders-api", **bounds})["stats"]


def test_half_open_window_includes_start_excludes_end(tmp_path, sample_rows):
    # Input order and string order differ from chronological order.
    tool = registry(tmp_path, list(reversed(sample_rows)))
    stats = analyze(tool, start_time="2026-10-20T09:00:01Z", end_time="2026-10-20T09:00:03Z")
    assert stats["requests"] == 2
    assert stats["status_counts"] == {"400": 1, "500": 1}
    assert stats["http_error_rate"] == 1.0
    assert stats["server_error_rate"] == 0.5
    assert stats["p95_ms"] == 30
    assert stats["sample_window"] == {"start_time": "2026-10-20T09:00:01Z", "end_time": "2026-10-20T09:00:02Z"}
    assert stats["requested_window"] == {"start_time": "2026-10-20T09:00:01Z", "end_time": "2026-10-20T09:00:03Z",
                                         "semantics": "[start_time,end_time)"}
    assert stats["window_start"] == stats["sample_window"]["start_time"]
    assert stats["window_end"] == stats["sample_window"]["end_time"]


def test_different_timezone_offsets_select_same_instants(tmp_path, sample_rows):
    tool = registry(tmp_path, sample_rows)
    utc = analyze(tool, start_time="2026-10-20T09:00:01Z", end_time="2026-10-20T09:00:03Z")
    offsets = analyze(tool, start_time="2026-10-20T14:30:01+05:30", end_time="2026-10-20T05:30:03-03:30")
    assert offsets == utc


@pytest.mark.parametrize("bounds,requests", [
    ({"start_time": "2026-10-20T09:00:02Z"}, 2),
    ({"end_time": "2026-10-20T09:00:02Z"}, 2),
])
def test_one_sided_windows(tmp_path, sample_rows, bounds, requests):
    assert analyze(registry(tmp_path, sample_rows), **bounds)["requests"] == requests


@pytest.mark.parametrize("bounds", [
    {"start_time": "2026-10-21T00:00:00Z", "end_time": "2026-10-22T00:00:00Z"},
    {"start_time": "2026-10-20T09:00:01Z", "end_time": "2026-10-20T09:00:01Z"},
])
def test_empty_window_returns_zero_and_no_invented_observations(tmp_path, sample_rows, bounds):
    stats = analyze(registry(tmp_path, sample_rows), **bounds)
    assert stats["requests"] == 0 and stats["empty_window"] is True
    assert stats["http_error_rate"] is None and stats["server_error_rate"] is None
    assert stats["p95_ms"] is None and stats["status_counts"] == {}
    assert stats["sample_window"] == {"start_time": None, "end_time": None}
    assert stats["window_start"] is None and stats["window_end"] is None
    assert stats["data_kind"] is None and stats["data_kind_counts"] == {}
    assert stats["requested_window"]["start_time"] == bounds["start_time"]


@pytest.mark.parametrize("bounds", [
    {"start_time": "2026-10-20T09:00:00"},
    {"end_time": "2026-10-20"},
    {"start_time": "not-a-time"},
    {"end_time": "2026-10-20T09:00:00+24:00"},
    {"start_time": 1792486800},
    {"start_time": True},
    {"start_time": "2026-10-20T09:00:01Z", "end_time": "2026-10-20T09:00:00Z"},
    {"start_time": "2026-10-20T10:00:00+01:00", "end_time": "2026-10-20T10:30:00+02:00"},
])
def test_invalid_time_bounds_rejected(bounds):
    with pytest.raises(ValueError):
        LogArgs.model_validate({"service": "orders-api", **bounds})


def test_service_allowlist_still_enforced():
    with pytest.raises(ValueError):
        LogArgs.model_validate({"service": "payments-api", "start_time": "2026-10-20T09:00:00Z"})


def test_legacy_csv_without_provenance_remains_compatible(tmp_path, sample_rows):
    stats = analyze(registry(tmp_path, sample_rows))
    assert stats["requests"] == 4
    assert stats["http_error_rate"] == 0.5 and stats["server_error_rate"] == 0.25
    assert stats["p95_ms"] == 40
    assert stats["data_kind"] == "synthetic_fixture"
    assert stats["data_kind_counts"] == {"synthetic_fixture": 4}
    assert stats["requested_window"]["start_time"] is None
    assert stats["requested_window"]["end_time"] is None
    assert stats["sample_window"] == {"start_time": "2026-10-20T09:00:00Z", "end_time": "2026-10-20T09:00:03Z"}
    assert "nearest-rank" in stats["statistics_policy"]["p95_ms"]


def test_new_csv_exposes_selected_data_provenance(tmp_path, sample_rows):
    for index, row in enumerate(sample_rows):
        row["data_kind"] = "synthetic_fixture" if index == 0 else "local_fault_injection"
    tool = registry(tmp_path, sample_rows, provenance=True)
    all_rows = analyze(tool)
    assert all_rows["data_kind"] == "mixed"
    assert all_rows["data_kind_counts"] == {"synthetic_fixture": 1, "local_fault_injection": 3}
    injected = analyze(tool, start_time="2026-10-20T09:00:01Z")
    assert injected["data_kind"] == "local_fault_injection"
    assert injected["data_kind_counts"] == {"local_fault_injection": 3}


def test_unknown_data_provenance_is_not_mislabeled(tmp_path, sample_rows):
    for row in sample_rows:
        row["data_kind"] = "production"
    with pytest.raises(ValueError, match="Unsupported log data_kind"):
        analyze(registry(tmp_path, sample_rows, provenance=True))


def test_p95_uses_nearest_rank_instead_of_interpolation(tmp_path):
    rows = [{"timestamp": f"2026-10-20T09:00:{i:02d}Z", "service": "orders-api", "status": 200,
             "latency_ms": i + 1, "request_id": str(i)} for i in range(20)]
    assert analyze(registry(tmp_path, rows))["p95_ms"] == 19


def test_empty_service_with_window_has_no_observations(tmp_path):
    tool = registry(tmp_path, [])
    assert analyze(tool, start_time="2026-10-20T09:00:00Z")["requests"] == 0
    with pytest.raises(ValueError, match="No fixture logs"):
        analyze(tool)


def test_tool_schema_describes_time_bounds():
    spec = next(item["function"] for item in TOOL_SPECS if item["function"]["name"] == "analyze_service_logs")
    for name in ("start_time", "end_time"):
        field = spec["parameters"]["properties"][name]
        assert {"format": "date-time", "type": "string"} in field["anyOf"]
        assert "时区" in field["description"]
    assert "[start_time,end_time)" in spec["description"]
