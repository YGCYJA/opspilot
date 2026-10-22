# Contributing

Use Python 3.11+ and Git, then install the development extra:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

The default tests do not download model weights or call an external model API. Use temporary directories for repositories, XML files, and report outputs.

## Reproduce the main workflow

```bash
python scripts/reproduce_pytest_demo.py --output-dir var/contribution_demo
opspilot triage --repo var/contribution_demo/project \
  --junit var/contribution_demo/junit.xml --base HEAD \
  --notes var/contribution_demo/project/docs \
  --output var/contribution_demo/report
```

The generator intentionally produces a failing cart boundary test and retains the passing baseline. It refuses to overwrite a non-empty directory. Inspect the XML, source, diff, and report together; a successful command alone does not establish that the report is useful.

## Changes

Keep pull requests focused on observable behavior. Describe the input, the resulting report, the checks run, and any remaining limits. Add regression coverage for changes to XML parsing, Git inputs, path boundaries, evidence references, model fallbacks, output formats, or installation. Do not add tests that merely repeat an implementation detail.

Do not commit credentials, private source, personal test logs, generated working directories, model weights, or external project reports. XML can contain secrets in failure text or captured output, so inspect fixtures before posting them. Use small authored examples when a real report cannot be shared.

When changing packaging, run `python -m build`, install the wheel in a fresh environment, and run `opspilot --help` from outside the checkout. Confirm that a user can analyze an explicitly supplied repository without access to development-only paths.

## Issues

Include the Python and Git versions, installation method, command or API payload, a minimal XML example where possible, and the expected/actual result. If source mapping is wrong, include only the minimal redacted directory structure and stack lines needed to reproduce it. Keep a failed optional model explanation separate from the deterministic report when reporting a model problem.

For a sensitive security issue, use GitHub's private vulnerability reporting if available. Do not publish a credential or private file in an issue.
