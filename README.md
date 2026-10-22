# OpsPilot

[![CI](https://github.com/YGCYJA/opspilot/actions/workflows/ci.yml/badge.svg)](https://github.com/YGCYJA/opspilot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An inspectable incident assistant that combines Markdown knowledge retrieval, read-only log analysis, and evidence-linked answers. Run it locally through a CLI or FastAPI, with an offline baseline and optional local or HTTP model backends.

[中文说明](README.zh-CN.md) · [Architecture](docs/architecture.md) · [Configuration](docs/configuration.md) · [API](docs/api.md) · [Evaluation](docs/evaluation.md) · [Fault lab](docs/fault-lab.md)

## What it does

- Retrieves Markdown passages with source filenames, line numbers, and content-based citation IDs.
- Compares BM25, character TF-IDF, lexical RRF fusion, and optional local embedding retrieval.
- Calculates request count, HTTP error rate, server error rate, and nearest-rank P95 from local CSV logs, with explicit time windows.
- Runs a bounded LangGraph workflow with two allowlisted read-only tools, citation quote checks, and visible fallback/refusal states.
- Records plans, tool results, evidence, latency, and model usage in a local SQLite run history.
- Includes reproducible retrieval evaluation and a real loopback HTTP fault experiment.

The bundled Chinese knowledge base describes fictional `orders-api` and `auth-api` services. Its CSV logs are synthetic fixtures. The fault lab produces actual local HTTP observations with intentionally injected faults. Neither dataset represents a production service.

## Quick start

Requires Python 3.11 or newer. The default installation needs no GPU, model weights, API key, or external model requests.

```bash
git clone https://github.com/YGCYJA/opspilot.git
cd opspilot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

opspilot ask '统计 orders-api 的请求数、错误率和 P95 延迟' --json
opspilot ask 'HTTP 401 应该如何排查？'
opspilot eval --split test --output reports/generated
python -m uvicorn opspilot.api:app --host 127.0.0.1 --port 8000
```

On Windows, activate with `.venv\Scripts\activate`. Open **http://127.0.0.1:8000/docs** to try the API.

For the bundled `orders-api` fixture, the statistics are 100 requests, HTTP error rate `0.2`, server error rate `0.1`, and P95 `1980.0` ms. Results include their data source and citation evidence. A bare error-rate request without a service asks for clarification.

```bash
opspilot ask '统计 orders-api 的请求数和错误率' \
  --start-time 2026-10-20T09:00:00Z \
  --end-time 2026-10-20T10:00:00Z --json
```

Bounds use **[start, end)** and require ISO8601 timestamps with a timezone. No rows means `requests=0` and `null` rates/P95; it does not mean a healthy service.

## Bring your own knowledge

Copy the example data and replace Markdown files in `knowledge/`:

```bash
cp -R data my-data
export OPS_DATA_DIR="$PWD/my-data"
export OPS_STATE_DIR="$PWD/var"
opspilot ingest
opspilot ask 'HTTP 429 应该如何处理？'
```

The app ingests Markdown at startup; `ingest` exports an inspectable JSON index, which is not a separate persisted search backend. Packaged installations also include the example data, so the CLI works outside the checkout. See [data resolution and the CSV contract](docs/configuration.md).

## Optional model backends

The default `OPS_MODE=offline` uses rule planning and extractive answers. Model planning and generation are opt-in:

```bash
# HTTP backend: a provider supporting tools and JSON response_format
export OPS_MODE=llm
export LLM_BASE_URL=https://your-provider.example/v1
export LLM_API_KEY=replace-locally
export LLM_MODEL=your-model-name
opspilot ask '统计 orders-api 的错误率' --json
```

Local generation uses a separately downloaded Qwen3 model. Semantic retrieval uses a separately downloaded BGE model. See [setup instructions](docs/configuration.md#optional-local-models). Downloads are explicit; model weights are excluded from this repository.

Inspect `mode`, `status`, `warnings`, and `trace`, not just the answer text. A model failure can produce `offline_fallback`; that result must not be counted as successful model generation. Citation checks validate source IDs and verbatim quotes, not semantic correctness.

## Reproduce and develop

```bash
python -m pytest -q
opspilot eval --split test --output reports/generated
python scripts/run_fault_lab.py --requests-per-scenario 5
python scripts/verify_fault_integration.py --output reports/generated/fault_lab

# Build an installable wheel
python -m pip install build
python -m build
```

The evaluation has 10 development cases and 36 test cases (24 retrieval, 6 tool, 6 unknown). It is a small authored fixture, not a production quality estimate. [Evaluation documentation](docs/evaluation.md) explains the metrics and separate model checks.

```text
opspilot/
├── opspilot/             # workflow, retrieval, tools, model adapters, API, CLI
│   └── resources/data/   # packaged copy of the example fixtures
├── data/                 # editable source fixtures and evaluation cases
├── scripts/              # downloads, evaluations, fault experiment runners
├── tests/                # unit, regression, time-window and HTTP integration tests
├── docs/                 # architecture, configuration, API and evaluation guides
├── .github/workflows/    # tests and distribution smoke checks
├── Dockerfile
├── pyproject.toml
└── requirements*.lock    # pinned environment snapshots
```

## Docker

```bash
docker build -t opspilot .
docker run --rm -p 127.0.0.1:8000:8000 opspilot
```

The image uses offline mode by default. Container state is ephemeral unless you mount a writable `/app/var` for the non-root application user. The API has no authentication: keep it on loopback for local use, or add authentication and access controls before exposing it to other users.

## Limits

Service names and statistical intent use explicit rules; the built-in log tool supports `orders-api` and `auth-api`. All retrieval is in memory and suitable for small corpora. The optional small local model is experimental. Quotes can be genuine while a conclusion is wrong; review consequential answers. Redaction covers known keys and common token patterns, not arbitrary sensitive content. See [architecture tradeoffs](docs/architecture.md#boundaries).

Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Code and bundled authored fixtures are distributed under the [MIT license](LICENSE). Downloaded models and dependencies keep their own licenses.
