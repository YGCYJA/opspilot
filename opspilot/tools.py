from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .retrieval import Retriever


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=1500)


class LogArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: Literal["orders-api", "auth-api"]
    start_time: datetime | None = Field(
        default=None, description="可选 ISO8601 时间（必须带时区），包含此时刻；例如 2026-10-20T09:00:00Z。"
    )
    end_time: datetime | None = Field(
        default=None, description="可选 ISO8601 时间（必须带时区），不包含此时刻；例如 2026-10-20T10:00:00+08:00。"
    )

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def require_iso_timezone(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Time bounds must be ISO8601 strings with a timezone")
        return _parse_timestamp(value)

    @model_validator(mode="after")
    def ordered_window(self):
        if self.start_time is not None and self.end_time is not None and self.start_time > self.end_time:
            raise ValueError("start_time must be before or equal to end_time")
        return self


def _parse_timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value)
    except (ValueError, TypeError) as error:
        raise ValueError("Time must be an ISO8601 datetime with a timezone") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Time must include a timezone, such as Z or +08:00")
    return timestamp


def _utc_text(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value is not None else None


SCHEMAS = {"search_knowledge": SearchArgs, "analyze_service_logs": LogArgs}
TOOL_SPECS = [{"type": "function", "function": {
    "name": name, "description": description, "parameters": SCHEMAS[name].model_json_schema()
}} for name, description in (
    ("search_knowledge", "检索本地演示运维知识库，回答故障原因、接入配置和处理步骤。"),
    ("analyze_service_logs", "统计本地日志中指定服务的请求数、HTTP错误率、P95延迟。可选start_time/end_time须为带时区ISO8601时间，范围为[start_time,end_time)，省略边界表示不限。结果区分合成样本与本地故障注入，非生产日志。")
)]


class ToolRegistry:
    def __init__(self, retriever: Retriever, logs: Path, method: str = "bm25"):
        self.retriever = retriever
        self.logs = logs
        self.method = method

    def execute(self, name: str, arguments: dict) -> dict:
        if name not in SCHEMAS:
            raise ValueError("Tool is not allowlisted")
        args = SCHEMAS[name].model_validate(arguments)
        if name == "search_knowledge":
            hits = self.retriever.search(args.query, k=5, method=self.method)
            return {"hits": hits}
        try:
            with self.logs.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                required = {"timestamp", "service", "status", "latency_ms"}
                if not required.issubset(reader.fieldnames or []):
                    raise ValueError("Log CSV is missing required timestamp, service, status or latency_ms columns")
                service_rows = []
                for row in reader:
                    if any(not isinstance(row.get(key), str) or not row[key].strip() for key in required):
                        raise ValueError("Log CSV rows must provide all required fields")
                    if row["service"] == args.service:
                        service_rows.append(row)
        except csv.Error:
            raise ValueError("Log CSV could not be parsed") from None
        if not service_rows and args.start_time is None and args.end_time is None:
            raise ValueError("No fixture logs for this service")
        timestamped_rows = []
        for row in service_rows:
            try:
                timestamp = _parse_timestamp(row["timestamp"])
            except ValueError:
                raise ValueError("Log timestamps must be ISO8601 datetimes with a timezone") from None
            status_text = row["status"].strip()
            if not re.fullmatch(r"[0-9]{3}", status_text) or not 100 <= int(status_text) <= 599:
                raise ValueError("Log status must be an HTTP integer between 100 and 599")
            try:
                latency = float(row["latency_ms"])
            except (ValueError, TypeError, OverflowError):
                raise ValueError("Log latency_ms must be a finite nonnegative number") from None
            if not math.isfinite(latency) or latency < 0:
                raise ValueError("Log latency_ms must be a finite nonnegative number")
            timestamped_rows.append(({**row, "status": str(int(status_text)), "latency_ms": latency}, timestamp))
        selected = [(row, timestamp) for row, timestamp in timestamped_rows
                    if (args.start_time is None or timestamp >= args.start_time)
                    and (args.end_time is None or timestamp < args.end_time)]
        rows = [row for row, _ in selected]
        kinds = Counter(row.get("data_kind") or "synthetic_fixture" for row in rows)
        if set(kinds) - {"synthetic_fixture", "local_fault_injection"}:
            raise ValueError("Unsupported log data_kind; expected synthetic_fixture or local_fault_injection")
        window_start = _utc_text(min(timestamp for _, timestamp in selected)) if selected else None
        window_end = _utc_text(max(timestamp for _, timestamp in selected)) if selected else None
        latencies = sorted(float(r["latency_ms"]) for r in rows)
        statuses = Counter(r["status"] for r in rows)
        stats = {
            "service": args.service,
            "data_kind": next(iter(kinds)) if len(kinds) == 1 else ("mixed" if kinds else None),
            "data_kind_counts": dict(sorted(kinds.items())),
            "requested_window": {"start_time": _utc_text(args.start_time), "end_time": _utc_text(args.end_time),
                                 "semantics": "[start_time,end_time)"},
            "sample_window": {"start_time": window_start, "end_time": window_end},
            "window_start": window_start,
            "window_end": window_end,
            "empty_window": not rows,
            "requests": len(rows),
            "http_error_rate": round(sum(int(r["status"]) >= 400 for r in rows) / len(rows), 4) if rows else None,
            "server_error_rate": round(sum(int(r["status"]) >= 500 for r in rows) / len(rows), 4) if rows else None,
            "p95_ms": latencies[math.ceil(.95 * len(rows)) - 1] if rows else None,
            "status_counts": dict(sorted(statuses.items())),
            "statistics_policy": {
                "scope": "selected service and requested time window; local CSV records only",
                "http_error_rate": "count(status >= 400) / requests, rounded to 4 decimals",
                "server_error_rate": "count(status >= 500) / requests, rounded to 4 decimals",
                "p95_ms": "nearest-rank: sorted_latency[ceil(0.95 * requests) - 1]",
                "sample_window": "first and last observed timestamps, inclusive; UTC",
                "empty_window": "requests = 0; rates, p95 and observed timestamps = null",
            },
        }
        return {"stats": stats, "text": json.dumps(stats, ensure_ascii=False, sort_keys=True)}
