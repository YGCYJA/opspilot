# Configuration

Settings are read from environment variables. `.env.example` documents them; the app does not automatically load `.env`. Use `export`, your process manager, or a tool that loads environment variables explicitly.

## Paths

Data resolution uses this order:

1. Explicit `data_dir` passed to `build_agent()` or `evaluate()`.
2. `OPS_DATA_DIR`.
3. `./data` when it contains a `knowledge/` directory.
4. Read-only example data bundled with the package.

An explicitly configured missing directory raises an error rather than silently switching to examples. Relative paths are relative to the process working directory. State resolution uses the explicit `state_dir`, then `OPS_STATE_DIR`, then `./var`. Default evaluations write to `./reports`. Package resources are never used as a writable state directory.

| Variable | Default | Purpose |
|---|---|---|
| `OPS_MODE` | `offline` | `offline`, `llm`, or `local` |
| `OPS_DATA_DIR` | resolved as above | directory containing `knowledge/` and `logs.csv` |
| `OPS_STATE_DIR` | `var` | SQLite and default exported index location |
| `OPS_LOG_FILE` | resolved data directory `/logs.csv` | alternate local fixture/experiment CSV |
| `OPS_RETRIEVER` | `bm25` | `bm25`, `tfidf`, `hybrid`, or `semantic` |
| `OPS_EMBED_MODEL` | unset | existing local SentenceTransformer directory |
| `OPS_EMBED_QUERY_PREFIX` | empty | model-specific query instruction |
| `LLM_BASE_URL` | unset | HTTP provider base URL ending in `/v1`, for example |
| `LLM_API_KEY` | unset | provider key for `llm` mode |
| `LLM_MODEL` | unset | provider model name |
| `OPS_LOCAL_MODEL` | unset | existing local chat model directory |
| `OPS_LOCAL_MAX_TOKENS` | `600` | local answer generation budget |

The HTTP backend requires HTTPS, except for explicit localhost/loopback development endpoints. URLs with embedded credentials, query parameters, or fragments are rejected. Requests use timeouts and at most two attempts for retryable provider/transport failures. A provider must support tool calls and JSON `response_format`; compatible URL shape alone does not guarantee compatibility.

## CSV contract

The read-only log tool supports `orders-api` and `auth-api` and expects UTF-8 CSV:

```csv
timestamp,service,status,latency_ms,data_kind
2026-10-20T09:00:00Z,orders-api,200,12.4,synthetic_fixture
2026-10-20T09:00:01Z,orders-api,503,80.2,synthetic_fixture
```

Timestamps require a timezone, HTTP status must be an integer from 100 to 599, and latency must be finite and non-negative. `data_kind` must be `synthetic_fixture` or `local_fault_injection`; a missing/empty value is treated as `synthetic_fixture` for compatibility. Preserve the actual provenance when creating data. A real production-log adapter would need an explicit provenance/schema extension.

Bounds are optional and use `[start_time,end_time)`. Equal bounds select no rows; reversed bounds are invalid. Both requested and observed windows are included in the result. The observed end is the last sample timestamp, not an exclusive query boundary.

HTTP errors count status `>=400`; server errors count status `>=500`. Rates are rounded to four decimals. P95 uses nearest rank `sorted_latency[ceil(0.95*n)-1]`. With no selected rows, rates, P95, and observed timestamps are `null` while request count is zero.

## Optional local models

Install from the checkout and download weights explicitly (network access and disk space required):

```bash
python -m pip install -e '.[local]'
python scripts/download_chat_model.py
export OPS_MODE=local
export OPS_LOCAL_MODEL="$PWD/var/models/Qwen3-0.6B"
opspilot ask 'HTTP 401 应该如何排查？' --json
```

The downloader pins `Qwen/Qwen3-0.6B` to revision `c1899de289a04d12100db370d81485cdf75e47ca`. The runtime loads local files, uses CPU float32, greedy decoding and non-thinking mode, and constrains answer JSON using LM Format Enforcer. Small models can produce malformed, truncated, or unsupported answers; check fallbacks and evaluate your workload.

For semantic retrieval only, install `.[semantic]`; the `local` extra also includes it:

```bash
python -m pip install -e '.[semantic]'
python scripts/download_embedding.py
export OPS_EMBED_MODEL="$PWD/var/models/bge-small-zh-v1.5"
export OPS_EMBED_QUERY_PREFIX='为这个句子生成表示以用于检索相关文章：'
export OPS_RETRIEVER=semantic
opspilot ask 'HTTP 429 应该如何处理？'
opspilot eval --semantic --output reports/generated
```

The downloader pins `BAAI/bge-small-zh-v1.5` to revision `7999e1d3359715c523056ef9478215996d62a620`. Runtime startup never downloads weights implicitly. Downloaded model licenses are separate from this repository's MIT license.

`requirements.lock`, `requirements-semantic.lock`, and `requirements-local.lock` are pinned Python 3.12 environment snapshots, not a universal multi-platform lock. The extras in `pyproject.toml` are the normal installation path. Use a fresh environment when switching dependency profiles. The local extra limits Transformers to `<5` for its structured-output integration.

## Troubleshooting

| Symptom | Check |
|---|---|
| Python/pip installation fails | use Python 3.11+ and a fresh virtual environment |
| No Markdown knowledge found | `OPS_DATA_DIR` must contain `knowledge/*.md` |
| Import error for optional model libraries | install the relevant extra in the active environment |
| Semantic mode requires a local model | download first and set `OPS_EMBED_MODEL` to that directory |
| SQLite write permission error | point `OPS_STATE_DIR` at a writable local directory |
| Time window returns 422 | supply a full date, time and timezone; start must not exceed end |
| Empty statistics | compare the requested window with actual timestamps in the CSV |
| Model fallback | inspect `warnings`, `trace`, provider capabilities and token budget |
| Fault tests cannot bind a port | permit a temporary loopback listener; no external listener is needed |
