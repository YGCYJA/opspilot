from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opspilot.agent import IncidentAgent
from opspilot.api import create_app
from opspilot.retrieval import Retriever, ingest
from opspilot.storage import Store
from opspilot.tools import ToolRegistry


@pytest.fixture
def agent(tmp_path):
    return IncidentAgent(ToolRegistry(Retriever(ingest(Path("data/knowledge"))), Path("data/logs.csv")), Store(tmp_path / "r.sqlite3"))


def test_question_window_reaches_tool(agent):
    result = agent.ask("统计orders-api日志，从2026-10-20T09:04:00Z到2026-10-20T09:05:00Z的错误率")
    assert result["log_stats"]["requests"] == 20
    assert result["log_stats"]["http_error_rate"] == 1
    assert result["log_stats"]["p95_ms"] == 2060


def test_api_structured_window_and_errors(agent):
    with TestClient(create_app(agent)) as client:
        response = client.post("/ask", json={"question": "统计orders-api日志错误率", "start_time": "2026-10-20T09:04:00Z", "end_time": "2026-10-20T09:05:00Z"})
        assert response.status_code == 200
        assert response.json()["log_stats"]["requests"] == 20
        for body in ({"start_time": "2026-10-20T09:00:00"},
                     {"start_time": "2026-10-21T00:00:00Z", "end_time": "2026-10-20T00:00:00Z"}):
            assert client.post("/ask", json={"question": "统计orders-api日志", **body}).status_code == 422


def test_empty_window_has_unknown_rates(agent):
    result = agent.ask("统计orders-api日志", start_time="2027-01-01T00:00:00Z")
    assert result["log_stats"]["requests"] == 0
    assert result["log_stats"]["http_error_rate"] is None
    assert result["log_stats"]["p95_ms"] is None


def test_explicit_window_preserves_session_memory_flag(agent):
    result = agent.ask("统计orders-api日志", start_time="2026-10-20T09:00:00+00:00")
    assert result["trace"][0]["used_session_context"] is False


def test_single_sided_question_window(agent):
    result = agent.ask("统计orders-api日志从2026-10-20T09:04:00Z起的请求数")
    assert result["log_stats"]["requests"] == 20
    result = agent.ask("统计orders-api日志截至2026-10-20T09:04:00Z的请求数")
    assert result["log_stats"]["requests"] == 80


@pytest.mark.parametrize("question", [
    "统计orders-api从2026-10-20T09:04:00到2026-10-20T09:05:00的日志",
    "统计orders-api从09:04起的日志",
    "统计orders-api在2026-10-20T09:04:00Z的日志",
])
def test_ambiguous_or_unzoned_time_does_not_query_all_rows(agent, question):
    with pytest.raises(ValueError):
        agent.ask(question)


def test_model_cannot_invent_unrequested_window(agent):
    class InventedWindowModel:
        calls = 0
        usage = {}

        def complete(self, *args, **kwargs):
            self.calls += 1
            return {"tool_calls": [
                {"function": {"name": "search_knowledge", "arguments": '{"query":"orders-api"}'}},
                {"function": {"name": "analyze_service_logs", "arguments": '{"service":"orders-api","start_time":"2026-10-20T09:04:00Z","end_time":"2026-10-20T09:05:00Z"}'}},
            ]}

    agent.model_factory = InventedWindowModel
    result = agent.ask("统计orders-api全部日志请求数")
    assert result["mode"] == "offline_fallback"
    assert result["log_stats"]["requests"] == 100
