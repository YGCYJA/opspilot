# Local HTTP API

```bash
python -m uvicorn opspilot.api:app --host 127.0.0.1 --port 8000
```

Open `/` for a local report form or `/docs` for interactive OpenAPI documentation. The service has no authentication and accepts paths on the server's filesystem. Keep it on loopback; it is not a public file-analysis endpoint.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | local input form and report view |
| GET | `/health` | local service readiness |
| POST | `/triage` | analyze selected local pytest artifacts |

## Analyze a failure

Run the example generator before using these example paths:

```bash
python scripts/reproduce_pytest_demo.py
curl -sS http://127.0.0.1:8000/triage \
  -H 'Content-Type: application/json' \
  -d '{
    "repo": "var/pytest_demo/project",
    "junit": "var/pytest_demo/junit.xml",
    "base_ref": "HEAD",
    "notes_dir": "var/pytest_demo/project/docs"
  }'
```

| Request field | Required | Meaning |
|---|---|---|
| `repo` | yes | existing local project directory |
| `junit` | yes | local pytest JUnit XML file |
| `base_ref` | no | explicit Git baseline, such as `HEAD` or `HEAD~1` |
| `notes_dir` | no | local directory of relevant Markdown project rules inside `repo` |
| `offline` | no | `true` skips the optional model regardless of `OPS_MODE` (default `false`) |

Relative paths resolve from the server process's working directory. The browser does not upload files, and the API does not fetch a GitHub URL. Do not supply an arbitrary remote path and expect it to be cloned.

The response is the report described in [architecture](architecture.md#report-contract). Inspect `status` before reading the hypotheses:

- `analysis_ready`: failure evidence was collected; the cause is still unverified.
- `no_failures`: the supplied XML contains no failures/errors to analyze.
- `invalid_input`: a required path or artifact could not be accepted.

HTTP 200 covers `analysis_ready` and `no_failures`. Invalid request fields, required local inputs, or model configuration return 422. A usable report can still have warnings about missing optional context.

`observations` and `hypotheses` reference entries in `evidence`. Every hypothesis remains `unverified`. `reproduction.executed` is `false`; the service does not execute that command. The `model` object and `warnings` expose whether optional explanation generation was used and whether it succeeded.

## Data handling

The analysis reads the selected local files and returns a report. There is no persistent conversation/run database. Save a report explicitly with the CLI when needed. The optional external model mode sends collected context to the configured provider; offline mode makes no model request.

Test failure text, source, and project notes can contain credentials or personal information. Common-pattern redaction is a useful reduction, not comprehensive detection. Review the collected context before enabling an external provider or sharing a response.
