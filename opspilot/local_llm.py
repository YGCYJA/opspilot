"""Actual local Transformers inference; no synthetic model responses.

The shared runtime loads weights once. Per-request wrappers keep independent
token counters and raw, non-thinking outputs for an auditable evaluation.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from .llm import ModelError
from .storage import redact_value

ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["claims"],
    "properties": {"claims": {"type": "array", "maxItems": 4, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["claim", "source_id", "quote"],
        "properties": {"claim": {"type": "string"}, "source_id": {"type": "string"},
                       "quote": {"type": "string", "minLength": 6}},
    }}},
}


def output_without_thinking(value: str) -> str:
    if "</think>" in value:
        value = value.rsplit("</think>", 1)[1]
    value = value.strip()
    if value.startswith("```json") and value.endswith("```"):
        value = value[len("```json"):-3].strip()
    elif value.startswith("```") and value.endswith("```"):
        value = value[3:-3].strip()
    return value


def parse_tool_output(value: str) -> list[dict]:
    """Parse only actual tool_call blocks; never invent a missing model action."""
    blocks = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", value, re.S)
    calls = []
    for i, block in enumerate(blocks):
        data = json.loads(block)
        if not isinstance(data, dict) or not isinstance(data.get("name"), str):
            raise ValueError("Invalid generated tool call")
        args = data.get("arguments")
        if isinstance(args, str):
            args = json.loads(args)
        if not isinstance(args, dict):
            raise ValueError("Invalid generated arguments")
        calls.append({"id": f"local-call-{i}", "type": "function", "function": {
            "name": data["name"], "arguments": json.dumps(args, ensure_ascii=False)}})
    return calls


class LocalRuntime:
    def __init__(self, model_path: Path, max_new_tokens=600, threads=4):
        if not model_path.is_dir():
            raise ValueError("OPS_LOCAL_MODEL must be an existing downloaded model directory")
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        torch.set_num_threads(max(1, min(threads, os.cpu_count() or 1)))
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True, trust_remote_code=False)
        self.model = AutoModelForCausalLM.from_pretrained(str(model_path), local_files_only=True,
                                                        trust_remote_code=False, dtype=torch.float32)
        self.model.eval()
        self.max_new_tokens = max_new_tokens
        self.lock = threading.Lock()
        self.path = model_path
        manifest = model_path / "opspilot_manifest.json"
        self.manifest = json.loads(manifest.read_text()) if manifest.exists() else {"local_directory": model_path.name}

    def generate(self, messages: list[dict], tools=None, json_mode=False):
        with self.lock, self.torch.inference_mode():
            started = time.perf_counter()
            text = self.tokenizer.apply_chat_template(messages, tools=tools, tokenize=False,
                                                      add_generation_prompt=True, enable_thinking=False)
            encoded = self.tokenizer([text], return_tensors="pt")
            prompt_tokens = int(encoded["input_ids"].shape[-1])
            max_tokens = min(self.max_new_tokens, 384 if tools else self.max_new_tokens)
            constraints = {}
            if json_mode:
                from lmformatenforcer import JsonSchemaParser
                from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn
                constraints["prefix_allowed_tokens_fn"] = build_transformers_prefix_allowed_tokens_fn(
                    self.tokenizer, JsonSchemaParser(ANSWER_SCHEMA))
            generated = self.model.generate(**encoded, max_new_tokens=max_tokens, do_sample=False,
                                             use_cache=True, pad_token_id=self.tokenizer.eos_token_id,
                                             eos_token_id=self.tokenizer.eos_token_id, **constraints)
            output_ids = generated[0, prompt_tokens:]
            value = output_without_thinking(self.tokenizer.decode(output_ids, skip_special_tokens=True))
            return {"output": value, "prompt_tokens": prompt_tokens, "completion_tokens": len(output_ids),
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    "hit_token_limit": len(output_ids) >= max_tokens, "schema_constrained": json_mode,
                    "last_token_id": int(output_ids[-1]) if len(output_ids) else None}


class LocalChatModel:
    backend = "local_transformers"

    def __init__(self, runtime: LocalRuntime):
        self.runtime = runtime
        self.calls = 0
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}
        self.records = []

    def complete(self, messages: list[dict], tools=None, json_mode=False):
        self.calls += 1
        try:
            generated = self.runtime.generate(messages, tools=tools, json_mode=json_mode)
            self.records.append(redact_value({"stage": "plan" if tools else "answer", "json_requested": json_mode, **generated}))
            for key in self.usage:
                self.usage[key] += generated[key]
            message = {"role": "assistant", "content": generated["output"]}
            if tools:
                message["tool_calls"] = parse_tool_output(generated["output"])
            return message
        except (ValueError, RuntimeError, TypeError, KeyError, ImportError, OSError):
            raise ModelError("Local model generation or tool-call parsing failed") from None
