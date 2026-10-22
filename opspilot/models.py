"""Optional explanation backend. Offline analysis needs no model dependency."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from .llm import ChatModel


def model_factory_from_env(force_offline: bool = False):
    mode = "offline" if force_offline else os.getenv("OPS_MODE", "offline")
    if mode == "offline":
        return None
    if mode == "llm":
        values = [os.getenv(key) for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")]
        if not all(values):
            raise ValueError("LLM mode requires LLM_BASE_URL, LLM_API_KEY and LLM_MODEL")
        # Validate configuration before creating an API request or reading project data.
        ChatModel(*values)
        return lambda: ChatModel(*values)
    if mode == "local":
        configured = os.getenv("OPS_LOCAL_MODEL")
        if not configured or not Path(configured).expanduser().is_dir():
            raise ValueError("local mode requires an existing OPS_LOCAL_MODEL directory")
        try:
            budget = int(os.getenv("OPS_LOCAL_MAX_TOKENS", "600"))
        except ValueError:
            raise ValueError("OPS_LOCAL_MAX_TOKENS must be an integer between 64 and 2048") from None
        if not 64 <= budget <= 2048:
            raise ValueError("OPS_LOCAL_MAX_TOKENS must be between 64 and 2048")
        runtimes, lock = [], threading.Lock()

        def factory():
            from .local_llm import LocalChatModel, LocalRuntime
            with lock:
                if not runtimes:
                    runtimes.append(LocalRuntime(Path(configured).expanduser(), max_new_tokens=budget))
            return LocalChatModel(runtimes[0])

        return factory
    raise ValueError("OPS_MODE must be offline, llm or local")
