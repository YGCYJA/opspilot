from __future__ import annotations

import os
from pathlib import Path

from .agent import IncidentAgent
from .llm import ChatModel
from .paths import resolve_data_dir, resolve_state_dir
from .retrieval import Retriever, ingest
from .storage import Store
from .tools import ToolRegistry


def build_agent(data_dir: Path | None = None, state_dir: Path | None = None, offline=False):
    data_dir = resolve_data_dir(data_dir)
    state_dir = resolve_state_dir(state_dir)
    chunks = ingest(data_dir / "knowledge")
    if not chunks:
        raise ValueError(f"No Markdown knowledge found in {data_dir / 'knowledge'}; check OPS_DATA_DIR")
    retriever = Retriever(chunks, os.getenv("OPS_EMBED_MODEL") or None, os.getenv("OPS_EMBED_QUERY_PREFIX", ""))
    method = os.getenv("OPS_RETRIEVER", "bm25")
    if method not in {"bm25", "tfidf", "hybrid", "semantic"}:
        raise ValueError("Invalid OPS_RETRIEVER")
    if method == "semantic" and retriever.encoder is None:
        raise ValueError("semantic mode requires a local OPS_EMBED_MODEL")
    mode = "offline" if offline else os.getenv("OPS_MODE", "offline")
    factory = None
    if mode == "llm":
        required = [os.getenv(k) for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")]
        if not all(required):
            raise ValueError("LLM mode requires LLM_BASE_URL, LLM_API_KEY and LLM_MODEL")
        factory = lambda: ChatModel(*required)
    elif mode == "local":
        from .local_llm import LocalChatModel, LocalRuntime
        model_path = os.getenv("OPS_LOCAL_MODEL")
        if not model_path:
            raise ValueError("local mode requires OPS_LOCAL_MODEL")
        runtime = LocalRuntime(Path(model_path), max_new_tokens=int(os.getenv("OPS_LOCAL_MAX_TOKENS", "600")))
        factory = lambda: LocalChatModel(runtime)
    elif mode != "offline":
        raise ValueError("OPS_MODE must be offline, llm or local")
    logs = Path(os.getenv("OPS_LOG_FILE", str(data_dir / "logs.csv")))
    agent = IncidentAgent(ToolRegistry(retriever, logs, method), Store(state_dir / "runs.sqlite3"), factory)
    agent.configured_mode = mode
    return agent
