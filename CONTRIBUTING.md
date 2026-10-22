# Contributing

Create a Python 3.11+ virtual environment and install the development extra:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
opspilot eval --split test --output reports/generated
```

Tests use temporary SQLite files and a loopback HTTP server. They do not download models or call external model APIs. Run tests in an environment where binding to `127.0.0.1` is permitted.

Keep changes focused and describe observable behavior, validation, and limitations in pull requests. Add regression coverage for behavior changes that affect evidence, time windows, statistics, model adapters, or installation. Do not commit credentials, private documents, local state, model weights, or generated logs from real systems.

## Fixture changes

`data/` is the editable fixture source. Keep its packaged copy in `opspilot/resources/data/` identical after modifying fixtures. Update relevant expected values and evaluation labels when changing CSV records or knowledge documents. Evaluation reports should identify dataset and source revisions; distinguish offline results from model results and retain failures.

Run `python -m build` to build source and wheel distributions. Install the wheel into a fresh virtual environment and run `opspilot ask`, `opspilot ingest`, and `opspilot eval` from outside the checkout when changing packaging or data resolution.

## Reporting issues

Include the Python version, installation method, mode, a minimal input, and the expected/actual result. Share redacted traces where useful; inspect them before posting. For a credential exposure or other sensitive security report, use GitHub's private vulnerability reporting if available and avoid posting the secret in a public issue.
