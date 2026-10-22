"""Small provider adapter: bounded retries, no credentials in exceptions/traces."""
from __future__ import annotations

import time
from urllib.parse import urlsplit

import httpx


class ModelError(RuntimeError):
    pass


class ChatModel:
    def __init__(self, base_url: str, api_key: str, model: str, transport=None):
        parsed = urlsplit(base_url)
        if not parsed.hostname or not (parsed.scheme == "https" or
                (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"})):
            raise ValueError("Use HTTPS or a localhost model endpoint")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Model endpoint must not contain credentials, a query or a fragment")
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.transport = transport
        self.calls = 0
        self.usage = {"prompt_tokens": None, "completion_tokens": None}

    def complete(self, messages: list[dict], tools: list[dict] | None = None, json_mode=False) -> dict:
        body = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": 1200}
        if tools:
            body.update(tools=tools, tool_choice="auto")
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        for attempt in range(2):
            self.calls += 1
            try:
                with httpx.Client(timeout=httpx.Timeout(25, connect=5), transport=self.transport) as client:
                    response = client.post(self.base_url + "/chat/completions", json=body,
                                           headers={"Authorization": "Bearer " + self.api_key})
                if response.status_code in {429, 500, 502, 503, 504} and attempt == 0:
                    time.sleep(.2)
                    continue
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Malformed provider response")
                usage = data.get("usage") or {}
                if not isinstance(usage, dict):
                    raise ValueError("Malformed provider usage")
                for key in self.usage:
                    reported = usage.get(key)
                    if reported is not None:
                        if not isinstance(reported, int) or isinstance(reported, bool) or reported < 0:
                            raise ValueError("Malformed provider token count")
                        self.usage[key] = (self.usage[key] or 0) + reported
                choices = data.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    raise ValueError("Malformed provider choices")
                message = choices[0]["message"]
                if not isinstance(message, dict):
                    raise ValueError("Malformed provider message")
                return message
            except (httpx.HTTPError, KeyError, ValueError, IndexError, TypeError) as error:
                if isinstance(error, httpx.TransportError) and attempt == 0:
                    time.sleep(.2)
                    continue
                raise ModelError("Model request failed; inspect provider configuration and availability") from None
        raise ModelError("Model request retry budget exhausted")
