# Changelog

## 0.2.0

- Focus the project on local pytest failure analysis for small Python repositories.
- Read JUnit XML, source context, an explicit optional Git baseline, and optional Markdown project rules.
- Separate observations, evidence, unverified hypotheses, missing context, and commands for the user to review.
- Provide a `triage` command, JSON/Markdown report export, and a local HTTP form/API.
- Keep the deterministic report usable without a model; make model explanation optional and expose its outcome.
- Add a reproducible cart boundary regression with actual passing and failing pytest artifacts.
- Remove the earlier service-log workflow, fictional service data, fault lab, old command/API surface, and SQLite run history from the current source tree.

### Interface migration

Use `opspilot triage --repo PATH --junit FILE` instead of the previous `ask`, `ingest`, or `eval` commands. The HTTP entry point is `POST /triage`. Input paths and the optional Git baseline are explicit; the old service names, time-window parameters, and log CSV contract no longer apply.

## 0.1.0

Initial incident-analysis prototype with Markdown retrieval, read-only CSV statistics, a bounded workflow, optional model adapters, and local HTTP fault experiments. This version remains in Git history; its inputs and evaluation results do not describe the current pytest workflow.
