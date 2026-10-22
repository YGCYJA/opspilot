from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opspilot.agent import IncidentAgent, verify_claims
from opspilot.api import create_app
from opspilot.evaluate import retrieval_metrics
from opspilot.retrieval import Retriever, ingest
from opspilot.storage import Store
from opspilot.tools import ToolRegistry


@pytest.fixture
def agent(tmp_path):
    return IncidentAgent(ToolRegistry(Retriever(ingest(Path("data/knowledge"))), Path("data/logs.csv")), Store(tmp_path / "runs.sqlite3"))


def test_ingest_provenance_and_update(tmp_path):
    file = tmp_path / "a.md"
    file.write_text("# Title\n## Heading\n凭据不能放进日志。\n", encoding="utf-8")
    original = ingest(tmp_path)[0]
    assert (original.doc_id, original.line_start, original.line_end) == ("a.md", 3, 3)
    file.write_text("# Title\n## Heading\n凭据应该被脱敏。\n", encoding="utf-8")
    assert ingest(tmp_path)[0].id != original.id


def test_large_lines_bounded(tmp_path):
    (tmp_path / "a.md").write_text("# Heading\n" + "长" * 2000, encoding="utf-8")
    assert all(len(c.text) <= 480 for c in ingest(tmp_path))
    assert "".join(c.text for c in ingest(tmp_path)) == "长" * 2000


def test_empty_retrieval():
    assert Retriever([]).search("API") == []


def test_auth_precise_retrieval(agent):
    assert agent.tools.retriever.search("HTTP 401 Authorization", 1)[0]["doc_id"] == "auth.md"


def test_multi_evidence_metric():
    assert retrieval_metrics(["a", "c", "d"], ["a", "b"])["recall_at_3"] == .5
    assert retrieval_metrics(["a", "c", "d"], ["a", "b"])["all_evidence_at_3"] == 0


@pytest.mark.parametrize("service,errors,p95", [("orders-api", .2, 1980), ("auth-api", .05, 238)])
def test_log_statistics(agent, service, errors, p95):
    stats = agent.tools.execute("analyze_service_logs", {"service": service})["stats"]
    assert stats["requests"] == 100
    assert stats["http_error_rate"] == errors
    assert stats["p95_ms"] == p95


@pytest.mark.parametrize("name,args", [("shell", {"command": "id"}), ("analyze_service_logs", {"service": "../../etc/passwd"}),
                                     ("search_knowledge", {"query": "a", "path": "/etc/passwd"})])
def test_tool_boundary(agent, name, args):
    with pytest.raises(ValueError):
        agent.tools.execute(name, args)


@pytest.mark.parametrize("claim", [
    {"claim": "foo", "quote": "supporting text", "source_id": "C:missing"},
    {"claim": "foo", "quote": "fabricated quotation", "source_id": "C:real"},
    {"claim": "foo", "quote": "supporting text", "source_id": []},
    {"claim": "", "quote": "supporting text", "source_id": "C:real"},
])
def test_citation_forgery_rejected(claim):
    assert not verify_claims([claim], [{"source_id": "C:real", "text": "supporting text"}])


def test_valid_citation():
    assert verify_claims([{"claim": "conclusion", "quote": "supporting text", "source_id": "C:real"}], [{"source_id": "C:real", "text": "supporting text"}])


def test_unknown_refuses(agent):
    assert agent.ask("明天广州会下雨吗")["status"] == "refused"


def test_session_memory_isolated(agent):
    agent.ask("统计orders-api日志错误率", "session-one")
    followup = agent.ask("再查它的P95延迟", "session-one")
    assert followup["log_stats"]["service"] == "orders-api"
    other = agent.ask("再查它的P95延迟", "session-two")
    assert other["service"] is None and other["log_stats"] == {}


def test_trace_saved_without_credentials(agent):
    result = agent.ask("HTTP 401，Bearer super-secret 和 sk-abcdefgh123456 应如何处理")
    stored = agent.store.get(result["run_id"])
    assert "super-secret" not in str(stored) and "sk-abcdefgh123456" not in str(stored)
    assert "[REDACTED]" in str(stored)


def test_api_contract_and_replay(agent):
    with TestClient(create_app(agent)) as client:
        assert client.get("/health").json()["status"] == "ok"
        result = client.post("/ask", json={"question": "统计orders-api日志错误率"}).json()
        assert result["status"] == "answered"
        assert client.get("/runs/" + result["run_id"]).json()["run_id"] == result["run_id"]
        assert client.get("/runs/missing").status_code == 404
        assert client.post("/ask", json={"question": " "}).status_code == 422
        assert client.post("/ask", json={"question": "a" * 1501}).status_code == 422
        assert client.post("/ask", json={"question": "hello", "session_id": "../unsafe"}).status_code == 422
