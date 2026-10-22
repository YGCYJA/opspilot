"""Regression coverage for model boundaries and truthful statistical answers."""
import csv
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from opspilot.agent import IncidentAgent
from opspilot.api import create_app
from opspilot.llm import ChatModel, ModelError
from opspilot.retrieval import Retriever, ingest
from opspilot.storage import Store
from opspilot.tools import ToolRegistry


def make_agent(tmp_path, reply=None, *, logs=None, key="release-test-key"):
    factory = None
    if reply is not None:
        def handle(request):
            message = reply(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": message}]})
        factory = lambda: ChatModel("https://test.example/v1", key, "test", httpx.MockTransport(handle))
    return IncidentAgent(ToolRegistry(Retriever(ingest(Path("data/knowledge"))), logs or Path("data/logs.csv")),
                         Store(tmp_path / "runs.sqlite3"), factory)


def search_call(query="orders-api"):
    return {"function": {"name": "search_knowledge", "arguments": json.dumps({"query": query})}}


def log_call(service="orders-api", **bounds):
    return {"function": {"name": "analyze_service_logs", "arguments": json.dumps({"service": service, **bounds})}}


def test_missing_model_statistics_action_is_audited_as_fallback(tmp_path):
    agent = make_agent(tmp_path, lambda body: {"tool_calls": [search_call()]})
    result = agent.ask("统计orders-api错误率")
    assert result["status"] == "answered"
    assert result["mode"] == "offline_fallback" and result["model_calls"] == 1
    assert result["log_stats"]["requests"] == 100
    assert result["trace"][1]["planner"] == "rules"
    assert [c["name"] for c in result["trace"][1]["model_proposed_calls"]] == ["search_knowledge"]


@pytest.mark.parametrize("question", ["统计错误率和P95", "错误率是多少", "P95延迟多高", "请求数是多少",
                                      "统计orders-api与auth-api的日志"])
def test_statistics_without_one_confirmed_service_requests_clarification(tmp_path, question):
    agent = make_agent(tmp_path, lambda body: pytest.fail("A clarification must not call the model"))
    result = agent.ask(question)
    assert result["status"] == "needs_clarification"
    assert result["mode"] == "offline" and result["model_calls"] == 0
    assert result["plan"] == [] and result["log_stats"] == {}
    assert result["trace"][1]["planner"] == "guardrail"


def test_metric_definition_is_not_a_service_statistics_request(tmp_path):
    result = make_agent(tmp_path).ask("HTTP错误率和服务端错误率有何区别")
    assert result["status"] == "answered" and not result["log_stats_required"]


def test_log_failure_cannot_be_replaced_with_a_document_answer(tmp_path):
    result = make_agent(tmp_path, logs=tmp_path / "missing.csv").ask("统计orders-api错误率")
    assert result["status"] == "refused" and result["claims"] == []
    assert any(t.get("name") == "analyze_service_logs" and not t["ok"] for t in result["trace"])


def test_generation_failure_does_not_claim_unrelated_document_answers(tmp_path):
    def reply(body):
        return {"tool_calls": [search_call()]} if "tools" in body else {"content": "not JSON"}
    result = make_agent(tmp_path, reply).ask("orders-api的研发负责人姓名是什么")
    assert result["evidence"]  # The shared service name retrieves an incident description.
    assert result["status"] == "refused" and result["claims"] == []
    assert result["mode"] == "offline_fallback"


def test_model_cannot_turn_an_empty_window_into_zero_error_rate(tmp_path):
    bounds = {"start_time": "2027-01-01T00:00:00Z"}
    def reply(body):
        if "tools" in body:
            return {"tool_calls": [search_call(), log_call(**bounds)]}
        evidence = json.loads(body["messages"][-1]["content"])["untrusted_evidence"]
        log = next(item for item in evidence if item["title"] == "演示日志统计")
        return {"content": json.dumps({"claims": [{"claim": "错误率为0%，服务健康", "source_id": log["source_id"],
                                                    "quote": log["text"]}]}, ensure_ascii=False)}
    result = make_agent(tmp_path, reply).ask("统计orders-api错误率", **bounds)
    assert result["mode"] == "offline_fallback" and result["status"] == "answered"
    assert result["log_stats"]["http_error_rate"] is None and result["data_kind"] is None
    assert "服务健康" not in result["answer"] and "0%" not in result["answer"]
    assert '"empty_window": true' in result["answer"]


@pytest.mark.parametrize("arguments", ["[]", "null", "not JSON"])
def test_nonobject_or_invalid_model_arguments_fall_back(tmp_path, arguments):
    reply = lambda body: {"tool_calls": [{"function": {"name": "search_knowledge", "arguments": arguments}}]}
    result = make_agent(tmp_path, reply).ask("HTTP 401怎么办")
    assert result["mode"] == "offline_fallback" and result["status"] == "answered"


@pytest.mark.parametrize("payload", [[], {"choices": [None]}, {"choices": [{"message": []}]},
                                     {"usage": [1], "choices": [{"message": {"content": "ok"}}]},
                                     {"usage": {"prompt_tokens": 1e999}, "choices": [{"message": {"content": "ok"}}]}])
def test_invalid_provider_schema_is_a_safe_model_error(payload):
    model = ChatModel("https://test.example/v1", "secret-key", "test",
                      httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    with pytest.raises(ModelError) as error:
        model.complete([])
    assert "secret-key" not in str(error.value)


def test_output_and_storage_redact_known_provider_key(tmp_path):
    secret = "provider-private-key-12345"
    def reply(body):
        if "tools" in body:
            return {"tool_calls": [search_call("HTTP 401")]}
        evidence = json.loads(body["messages"][-1]["content"])["untrusted_evidence"][0]
        return {"content": json.dumps({"claims": [{"claim": secret, "source_id": evidence["source_id"],
                                                    "quote": evidence["text"]}]})}
    agent = make_agent(tmp_path, reply, key=secret)
    result = agent.ask("HTTP 401怎么办")
    assert secret not in json.dumps(result)
    assert secret not in json.dumps(agent.store.get(result["run_id"]))


def test_api_does_not_echo_invalid_input_credentials(tmp_path):
    with TestClient(create_app(make_agent(tmp_path))) as client:
        result = client.post("/ask", json={"question": "hello", "session_id": "Bearer private-input-secret"})
    assert result.status_code == 422
    assert "private-input-secret" not in result.text and '"input"' not in result.text


@pytest.mark.parametrize("changes", [
    {"latency_ms": "nan"}, {"latency_ms": "inf"}, {"latency_ms": "-1"},
    {"status": "n/a"}, {"status": "99"}, {"status": "600"},
    {"timestamp": "private-invalid-timestamp"},
])
def test_invalid_csv_values_are_refused_without_api_serialization_failure(tmp_path, changes):
    path = tmp_path / "logs.csv"
    row = {"timestamp": "2026-10-20T09:00:00Z", "service": "orders-api", "status": "200", "latency_ms": "10"}
    row.update(changes)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    agent = make_agent(tmp_path, logs=path)
    with pytest.raises(ValueError) as error:
        agent.tools.execute("analyze_service_logs", {"service": "orders-api"})
    assert "private-invalid-timestamp" not in str(error.value)
    with TestClient(create_app(agent)) as client:
        response = client.post("/ask", json={"question": "统计orders-api的错误率和P95"})
    assert response.status_code == 200
    assert response.json()["status"] == "refused" and response.json()["log_stats"] == {}
    assert "private-invalid-timestamp" not in response.text


def test_csv_missing_required_columns_raises_a_clear_safe_error(tmp_path):
    path = tmp_path / "logs.csv"
    path.write_text("service,status\norders-api,200\n", encoding="utf-8")
    agent = make_agent(tmp_path, logs=path)
    with pytest.raises(ValueError, match="missing required"):
        agent.tools.execute("analyze_service_logs", {"service": "orders-api"})
