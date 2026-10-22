import json
from pathlib import Path

import httpx

from opspilot.agent import IncidentAgent
from opspilot.llm import ChatModel, ModelError
from opspilot.retrieval import Retriever, ingest
from opspilot.storage import Store
from opspilot.tools import ToolRegistry


def test_provider_transient_retry_and_usage():
    seen = []

    def handle(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2}})

    model = ChatModel("https://test.example/v1", "fake-key", "test-model", httpx.MockTransport(handle))
    assert model.complete([{"role": "user", "content": "hi"}])["content"] == "ok"
    assert model.calls == 2 and model.usage["prompt_tokens"] == 10
    assert seen[0].url.path == "/v1/chat/completions"


def test_nonretryable_error_redacted():
    model = ChatModel("https://test.example/v1", "secret-key", "test", httpx.MockTransport(lambda r: httpx.Response(401, text="secret-key")))
    try:
        model.complete([])
        assert False
    except ModelError as error:
        assert "secret-key" not in str(error) and model.calls == 1


def test_missing_usage_is_unknown():
    model = ChatModel("https://test.example/v1", "fake", "test", httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})))
    model.complete([])
    assert model.usage["prompt_tokens"] is None


def test_model_plan_and_grounded_answer(tmp_path):
    retriever = Retriever(ingest(Path("data/knowledge")))
    hit = retriever.search("HTTP 401 Authorization", 1)[0]
    quote = hit["text"].split("\n")[0]

    def handle(request):
        payload = json.loads(request.content)
        if "tools" in payload:
            message = {"tool_calls": [{"function": {"name": "search_knowledge", "arguments": json.dumps({"query": "HTTP 401 Authorization"})}}]}
        else:
            message = {"content": json.dumps({"claims": [{"claim": "检查鉴权请求头与密钥有效性", "quote": quote, "source_id": "C:" + hit["id"]}]}, ensure_ascii=False)}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    factory = lambda: ChatModel("https://test.example/v1", "fake", "test", httpx.MockTransport(handle))
    agent = IncidentAgent(ToolRegistry(retriever, Path("data/logs.csv")), Store(tmp_path / "runs.sqlite3"), factory)
    result = agent.ask("HTTP 401怎么办")
    assert result["mode"] == "llm" and result["status"] == "answered"
    assert result["model_calls"] == 2
    assert result["trace"][1]["planner"] == "model"


def test_invalid_model_plan_falls_back_explicitly(tmp_path):
    factory = lambda: ChatModel("https://test.example/v1", "fake", "test", httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "invalid"}}]})))
    agent = IncidentAgent(ToolRegistry(Retriever(ingest(Path("data/knowledge"))), Path("data/logs.csv")), Store(tmp_path / "r.sqlite3"), factory)
    result = agent.ask("HTTP 401怎么办")
    assert result["mode"] == "offline_fallback" and result["status"] == "answered"
    assert result["warnings"] and result["model_calls"] == 1
