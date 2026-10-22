# Configuration

The main inputs are explicit CLI options or API fields. Model settings are environment variables. `.env.example` is a reference file; the application does not automatically load `.env`.

## Local input paths

| CLI option | API field | Purpose |
|---|---|---|
| `--repo` | `repo` | existing local project directory |
| `--junit` | `junit` | pytest JUnit XML from that project |
| `--base` | `base_ref` | optional explicit Git comparison baseline |
| `--notes` | `notes_dir` | optional Markdown rules directory inside `repo` |
| `--output` | — | directory for `report.json` and `report.md` |
| `--offline` | `offline` | explicitly skip the optional model |
| `--json` | — | print JSON instead of Markdown |

Paths are resolved relative to the current process working directory. In the HTTP interface, this means the server's machine and working directory. A repository and XML are required. The selected repository and XML must not themselves be symbolic links; source and notes cannot traverse links inside the repository. OS aliases above the repository, such as macOS `/tmp`, are resolved before enforcing the boundary. The XML may be outside the repository, but source and notes must stay inside it. Git comparison requires the selected directory to be a work-tree root, including an ordinary linked worktree; it does not search a parent repository. Notes and Git context are optional; missing or uncollectable context must remain visible in the report.

Choose a baseline that matches your investigation. `HEAD` is useful for an uncommitted change; `HEAD~1` includes changes since the preceding commit. A branch or tag can also identify a baseline. OpsPilot does not infer which reference is known to pass the supplied tests.

The analysis command never runs the target project's code. Generate the XML yourself with `python -m pytest --junitxml=...`. The separate demo script runs only its own generated example. It does not accept an arbitrary shell command.

## Offline mode

```bash
export OPS_MODE=offline
opspilot triage --repo /path/to/project --junit /path/to/project/junit.xml
```

This is the default; `--offline` explicitly overrides `OPS_MODE`. Source context, diffs, retrieved rules, observations, and reproduction suggestions do not require a model. No model request is made and no model weights are downloaded at startup. Without `--output`, no report directory is explicitly requested; use the CLI output for inspection.

## Optional HTTP explanation

```bash
export OPS_MODE=llm
export LLM_BASE_URL=https://your-provider.example/v1
export LLM_API_KEY=replace-locally
export LLM_MODEL=your-model-name
opspilot triage --repo /path/to/project --junit /path/to/project/junit.xml --base HEAD
```

The provider must implement the Chat Completions endpoint and JSON `response_format`. Tool calling is not needed for failure analysis: evidence is collected before the explanation request. Compatible endpoint naming alone does not guarantee compatible responses.

The adapter uses HTTPS, with an exception for explicit local development endpoints at `http://127.0.0.1` or `http://localhost`. URLs containing embedded credentials, query parameters, or fragments are rejected. Requests are bounded by a timeout and retry budget. Credentials belong in local environment variables and must not be committed.

The provider receives collected report context, which can include failure text, source snippets, diffs, and notes. A model explanation is still an unverified hypothesis. A request or validation failure must remain visible rather than becoming a successful model result.

## Optional local explanation

```bash
python -m pip install -e '.[local]'
export OPS_MODE=local
export OPS_LOCAL_MODEL=/path/to/already-downloaded/chat-model
opspilot triage --repo /path/to/project --junit /path/to/project/junit.xml --base HEAD
```

`OPS_LOCAL_MODEL` must point to existing compatible local weights and tokenizer files. Runtime loading uses local files only and disables remote model code. The adapter uses CPU inference and a structured-output constraint; `OPS_LOCAL_MAX_TOKENS` controls the generation budget (default `600`). A small model can still truncate an answer or produce an explanation that fails validation. Model files are not distributed with this repository and retain their original licenses.

Check the report's `model` object and warnings. A valid deterministic report does not imply that the optional explanation succeeded. Default automated tests validate adapter behavior without loading real weights.

## Troubleshooting

| Symptom | Check |
|---|---|
| Package installation fails | use Python 3.11+ in a fresh virtual environment |
| Git context is missing | Git is installed; the directory is a repository; the explicit reference exists |
| No failure is found | the supplied XML is from the failing run and contains failure/error elements |
| Source context is missing | the XML/traceback names a file inside the selected repository |
| Unexpected source text | the source may have changed after the XML was generated; rerun pytest yourself |
| Demo output directory is rejected | use a new `--output-dir`; the generator does not overwrite existing evidence |
| HTTP cannot find local files | paths refer to the server process, not the browser device |
| Optional explanation fails | check model configuration, provider JSON support, dependencies, and report warnings |
| Local model import fails | install `.[local]` in the active environment and use compatible downloaded files |

Version 0.2 replaces the earlier incident/log workflow. The old `ask`, `ingest`, and `eval` commands, service CSV schema, and SQLite run history are not part of the current interface. See [CHANGELOG.md](../CHANGELOG.md).
