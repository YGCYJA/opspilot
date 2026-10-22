# HTTP API

```bash
python -m uvicorn opspilot.api:app --host 127.0.0.1 --port 8000
```

Interactive OpenAPI documentation is at `/docs`; `/` redirects there. Configuration is loaded at application startup. The API has no authentication; use a trusted local environment or put appropriate authentication and access controls in front of it.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | configured mode, retriever and chunk count |
| POST | `/ask` | execute a workflow and persist its run |
| GET | `/search?q=...&k=5` | direct ranked passages (`1 <= k <= 10`) |
| GET | `/documents` | available document IDs and chunk count |
| GET | `/runs/{run_id}` | retrieve a persisted run; 404 if absent |

## Ask

```bash
curl -sS http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"统计 orders-api 的错误率和 P95 延迟","session_id":"demo-session"}'
```

`question` is required, non-blank, and at most 1500 characters. Optional `session_id` accepts 1–64 ASCII letters, digits, underscores and hyphens; omission creates a new session. Optional `start_time` and `end_time` are ISO8601 timestamps with timezone offsets, such as `2026-10-20T09:00:00Z`.

```json
{
  "question": "统计 orders-api 的请求数",
  "session_id": "window-demo",
  "start_time": "2026-10-20T09:00:00Z",
  "end_time": "2026-10-20T10:00:00Z"
}
```

Important response fields:

| Field | Meaning |
|---|---|
| `run_id`, `session_id` | identifiers for this run and follow-up context |
| `status` | `answered`, `refused`, or `needs_clarification` |
| `mode`, `model_backend` | actual workflow/fallback mode and model implementation |
| `answer`, `claims` | output text and individual claims with evidence quotes |
| `evidence` | retrieved passages and deterministic tool observations |
| `plan`, `trace` | selected calls, proposed calls when available, and execution outcomes |
| `log_stats` | selected service/window statistics, or an empty object without log observation |
| `data_kind` | provenance (`null` for an empty log window) |
| `warnings` | fallback and tool failure details |
| `latency_ms`, `model_calls`, `usage` | timing and adapter usage (provider usage may be unavailable) |

HTTP 200 means the workflow ran; check `status` for the application outcome. A refused answer or clarification is a normal 200 response. Invalid request fields or time bounds return 422. Validation responses omit raw input to reduce accidental credential exposure. Source evidence and saved traces may still contain sensitive material outside the redaction patterns; inspect before sharing.

`/health.mode` reports the configured mode (`local` is possible); `/ask.mode` reports whether the actual workflow used a model, offline extraction or fallback. These fields serve different purposes.
