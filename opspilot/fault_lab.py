"""Controlled local HTTP fault injection with measured, provenance-labelled logs.

No external services are contacted. An HTTP 200 after a client timeout records
the server's completed response; it does not imply the client received it.
"""
from __future__ import annotations

import asyncio
import csv
import json
import math
import re
import socket
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


DATA_KIND = "local_fault_injection"
SCENARIOS = ("normal", "slow", "rate_limit", "unavailable", "timeout")
CSV_FIELDS = ("timestamp", "service", "status", "latency_ms", "request_id",
              "data_kind", "scenario", "run_id")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class CsvRecorder:
    """Write completed server requests and allow the driver to await completion."""

    def __init__(self, path: Path, run_id: str):
        self.path = path
        self.run_id = run_id
        self.rows: list[dict] = []
        self.condition = threading.Condition()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=CSV_FIELDS).writeheader()

    def append(self, row: dict) -> None:
        with self.condition:
            with self.path.open("a", encoding="utf-8", newline="") as handle:
                csv.DictWriter(handle, fieldnames=CSV_FIELDS).writerow(row)
            self.rows.append(row)
            self.condition.notify_all()

    def wait_for_count(self, expected: int, timeout: float = 5.0) -> None:
        with self.condition:
            if not self.condition.wait_for(lambda: len(self.rows) >= expected, timeout=timeout):
                raise TimeoutError(f"Only {len(self.rows)} of {expected} server requests completed")

    def snapshot(self) -> list[dict]:
        with self.condition:
            return [dict(row) for row in self.rows]


def create_fault_app(recorder: CsvRecorder) -> FastAPI:
    app = FastAPI(title="OpsPilot local fault laboratory")

    @app.middleware("http")
    async def record_order(request: Request, call_next):
        if request.url.path != "/orders":
            return await call_next(request)
        timestamp = utc_now()
        started = time.perf_counter()
        supplied_id = request.headers.get("x-lab-request-id", "")
        request_id = supplied_id if re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", supplied_id) else uuid4().hex
        response = await call_next(request)
        scenario = request.headers.get("x-lab-scenario", "normal")
        recorder.append({
            "timestamp": timestamp, "service": "orders-api", "status": response.status_code,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "request_id": request_id, "data_kind": DATA_KIND,
            "scenario": scenario if scenario in SCENARIOS else "rejected",
            "run_id": recorder.run_id,
        })
        response.headers["X-Lab-Request-Id"] = request_id
        return response

    @app.get("/health")
    async def health():
        return {"status": "ok", "data_kind": DATA_KIND, "run_id": recorder.run_id}

    @app.get("/orders")
    async def orders(request: Request):
        scenario = request.headers.get("x-lab-scenario", "normal")
        if scenario not in SCENARIOS:
            return JSONResponse({"error": "Unsupported lab scenario", "data_kind": DATA_KIND}, status_code=400)
        if scenario == "slow":
            await asyncio.sleep(0.050)
        elif scenario == "timeout":
            await asyncio.sleep(0.080)
        status = {"rate_limit": 429, "unavailable": 503}.get(scenario, 200)
        return JSONResponse({"orders": [], "scenario": scenario, "data_kind": DATA_KIND},
                            status_code=status,
                            headers={"Retry-After": "1"} if status == 429 else None)

    return app


class LocalFaultServer:
    """Bind only to loopback; hand the pre-bound socket to a uvicorn thread."""

    def __init__(self, recorder: CsvRecorder, port: int = 0):
        self.recorder = recorder
        self.port = port
        self.sock: socket.socket | None = None
        self.thread: threading.Thread | None = None
        self.server: uvicorn.Server | None = None
        self.base_url = ""

    def __enter__(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.bind(("127.0.0.1", self.port))
            self.sock.listen(128)
            self.base_url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
            self.server = uvicorn.Server(uvicorn.Config(
                create_fault_app(self.recorder), log_level="error", access_log=False,
                timeout_graceful_shutdown=2,
            ))
            self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]},
                                           name="opspilot-fault-lab", daemon=True)
            self.thread.start()
            deadline = time.monotonic() + 5.0
            with httpx.Client(trust_env=False, timeout=0.2) as client:
                while time.monotonic() < deadline:
                    if not self.thread.is_alive():
                        raise RuntimeError("Local fault server stopped before becoming ready")
                    try:
                        response = client.get(self.base_url + "/health")
                        if response.status_code == 200 and response.json().get("run_id") == self.recorder.run_id:
                            return self
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.02)
            raise TimeoutError("Local fault server did not become ready within 5 seconds")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout=5.0)
        if self.sock is not None:
            self.sock.close()
        if self.thread is not None and self.thread.is_alive():
            raise RuntimeError("Local fault server could not be stopped")

    def __exit__(self, *exc):
        self.close()


def _scenario_statistics(rows: list[dict]) -> dict:
    latencies = sorted(float(row["latency_ms"]) for row in rows)
    return {
        "requests": len(rows),
        "status_counts": dict(sorted(Counter(str(row["status"]) for row in rows).items())),
        "http_error_rate": round(sum(int(row["status"]) >= 400 for row in rows) / len(rows), 4),
        "p95_ms": latencies[math.ceil(0.95 * len(rows)) - 1],
        "first_log_timestamp": min(row["timestamp"] for row in rows),
        "last_log_timestamp": max(row["timestamp"] for row in rows),
    }


def run_experiment(output_dir: Path = Path("var/fault_lab"), requests_per_scenario: int = 5,
                   port: int = 0) -> dict:
    """Send actual local HTTP requests and persist separate client/server evidence."""
    if not 1 <= requests_per_scenario <= 100:
        raise ValueError("requests_per_scenario must be between 1 and 100")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    run_dir = output_dir.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    recorder = CsvRecorder(run_dir / "logs.csv", run_id)
    observations: list[dict] = []
    summary = {
        "run_id": run_id, "data_kind": DATA_KIND, "started_at": utc_now(),
        "note": "本地受控故障注入；不是企业生产事故。HTTP状态由服务端记录，客户端超时另列。",
        "requests_per_scenario": requests_per_scenario, "scenarios": [],
        "artifacts": {name: str(run_dir / name) for name in
                      ("logs.csv", "client_observations.json", "summary.json", "report.md")},
    }
    with LocalFaultServer(recorder, port=port) as server:
        summary["base_url"] = server.base_url
        with httpx.Client(trust_env=False, timeout=2.0) as client:
            for scenario in SCENARIOS:
                start_time = utc_now()
                offset = len(observations)
                for index in range(requests_per_scenario):
                    request_id = f"{run_id}-{scenario}-{index:03d}"
                    observation = {
                        "request_id": request_id, "scenario": scenario,
                        "run_id": run_id, "data_kind": DATA_KIND,
                        "started_at": utc_now(), "status": None,
                        "outcome": "response", "exception_type": None,
                    }
                    started = time.perf_counter()
                    try:
                        response = client.get(server.base_url + "/orders", headers={
                            "X-Lab-Scenario": scenario, "X-Lab-Request-Id": request_id,
                        }, timeout=0.030 if scenario == "timeout" else 2.0)
                        observation["status"] = response.status_code
                    except httpx.TimeoutException as exc:
                        observation.update(outcome="client_timeout", exception_type=type(exc).__name__)
                    except httpx.HTTPError as exc:
                        observation.update(outcome="transport_error", exception_type=type(exc).__name__)
                    finally:
                        observation["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
                        observation["ended_at"] = utc_now()
                        observations.append(observation)
                # A timed-out client does not cancel the server handler in this lab.
                # Wait for the actual handler completion before closing its window.
                recorder.wait_for_count(len(observations))
                end_time = utc_now()
                scenario_rows = [row for row in recorder.snapshot() if row["scenario"] == scenario]
                summary["scenarios"].append({
                    "scenario": scenario, "start_time": start_time, "end_time": end_time,
                    **_scenario_statistics(scenario_rows),
                    "client_timeout_count": sum(row["outcome"] == "client_timeout" for row in observations[offset:]),
                    "transport_error_count": sum(row["outcome"] == "transport_error" for row in observations[offset:]),
                    "query_arguments": {"service": "orders-api", "start_time": start_time, "end_time": end_time},
                })
    summary["finished_at"] = utc_now()
    summary["server_requests"] = len(recorder.snapshot())
    summary["client_requests"] = len(observations)
    # Persist portable references; absolute paths remain only in the return value
    # for callers opening the artifacts immediately after this run.
    portable_summary = {**summary, "artifacts": {name: name for name in summary["artifacts"]}}
    for filename, payload in (("client_observations.json", observations), ("summary.json", portable_summary)):
        (run_dir / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = ["# OpsPilot 本地故障注入实测", "", summary["note"], "",
              f"- run_id：`{run_id}`", f"- 服务地址：`{summary['base_url']}`（实验完成后已关闭）",
              f"- 开始：{summary['started_at']}", f"- 完成：{summary['finished_at']}", "",
              "| 场景 | 服务端请求数 | 服务端状态分布 | HTTP错误率 | 实测P95(ms) | 客户端超时数 |",
              "|---|---:|---|---:|---:|---:|"]
    for row in summary["scenarios"]:
        report.append(f"| {row['scenario']} | {row['requests']} | {json.dumps(row['status_counts'])} | "
                      f"{row['http_error_rate']:.0%} | {row['p95_ms']} | {row['client_timeout_count']} |")
    report += ["", "服务端延迟由 perf_counter 实测，时间戳由运行时 UTC 时钟生成。客户端超时不被改写为 HTTP 504。",
               "timeout 场景服务端仍完成 200；client_observations.json 记录客户端是否在收到响应前超时。",
               "", "## 按场景查询的实际时间窗口", ""]
    for row in summary["scenarios"]:
        report += [f"### {row['scenario']}", "", "```json",
                   json.dumps(row["query_arguments"], ensure_ascii=False, indent=2), "```", ""]
    (run_dir / "report.md").write_text("\n".join(report), encoding="utf-8")
    return summary
