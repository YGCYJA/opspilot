# Local HTTP fault lab

The lab starts a temporary HTTP server bound to `127.0.0.1` on an OS-assigned port, sends real HTTP requests, and shuts down the server. It does not contact or modify an external service.

```bash
python scripts/run_fault_lab.py --requests-per-scenario 5
python scripts/verify_fault_integration.py --output reports/generated/fault_lab
```

The first command prints the run ID and artifact locations under `var/fault_lab/`. The second selects the latest source-checkout run by default. To use a specific run:

```bash
python scripts/verify_fault_integration.py \
  --summary var/fault_lab/RUN_ID/summary.json \
  --output reports/generated/fault_lab
```

## Scenarios

| Scenario | Behavior |
|---|---|
| normal | ordinary HTTP 200 response |
| slow | HTTP 200 after an injected delay of about 50 ms |
| rate_limit | HTTP 429 |
| unavailable | HTTP 503 |
| timeout | server delay of about 80 ms, client timeout of about 30 ms |

Default execution sends 25 requests total. Timings vary by machine. Client timeouts and final server statuses are separate observations: a client may time out while the server later records HTTP 200. Treating that pair as one HTTP status would lose information.

Each run produces `logs.csv`, `client_observations.json`, `summary.json`, and `report.md`. Server rows have `data_kind=local_fault_injection`. Summary windows cover each scenario, allowing the same CSV statistics tool to analyze the selected interval.

The integration runner checks exact agreement between scenario statistics and agent tool results, checks provenance, verifies citation quotes, and produces `integration.json` and `integration.md` with source hashes. It uses rule planning/extractive output; model behavior is evaluated separately.

## Query the experiment

Point the app at one run's CSV and use a scenario's `query_arguments` from `summary.json`:

```bash
export OPS_LOG_FILE="$PWD/var/fault_lab/RUN_ID/logs.csv"
opspilot ask '统计 orders-api 的错误率和 P95 延迟' \
  --start-time START_FROM_SUMMARY --end-time END_FROM_SUMMARY --json
```

Replace the placeholders with actual timestamps. The app does not interpret relative time phrases such as “last five minutes” as an authoritative time range. Pass structured bounds for reproducible queries.

This experiment demonstrates controlled faults and the observation pipeline. It does not reproduce production traffic, concurrent load, distributed traces, or a production incident. Raw runtime output is ignored by Git; review generated reports before sharing them.
