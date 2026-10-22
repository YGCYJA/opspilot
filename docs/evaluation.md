# Evaluation

## Offline baseline

```bash
opspilot eval --split test --output reports/generated
```

This command never calls a model provider, even if `OPS_MODE=llm` is configured. It builds an explicit offline agent and compares retrieval methods. The source fixtures contain 13 Markdown documents, 40 chunks, 10 development cases and 36 test cases (24 retrieval, 6 tool, 6 unknown). Report hashes identify the corpus and dataset used.

The command creates `test_results.json` and `test_report.md`. JSON includes individual retrieval rankings, agent cases, environment details, latency and limitations. Use `--split dev` for development cases. `--semantic` explicitly adds a local embedding model and requires `OPS_EMBED_MODEL`.

## Metrics

| Metric | Definition |
|---|---|
| Recall@3 | fraction of labeled relevant documents in the top 3 distinct documents |
| MRR | reciprocal rank of the first relevant document in the full distinct-document ranking |
| nDCG@3 | binary relevance gain in the top 3, discounted by rank |
| All evidence@3 | whether every labeled relevant document occurs in the top 3 |
| Tool exact match | service and expected deterministic numeric statistics match |
| Correct refusal | listed unknown questions yield `refused` |
| Citation quote validity | source ID exists and quote occurs verbatim in that source |

Ranking first retrieves all chunks and deduplicates by document before scoring. In contrast, the actual agent consumes at most five search chunks. The reporting difference is explicit and matters when comparing retrieval scores with answers.

Retrieval latency is the median of five warm searches per case, aggregated into P50/P95. End-to-end offline agent latency includes graph execution and SQLite commits, but excludes model inference, process startup and initial indexing. Hardware affects these measurements.

## Real model checks

Local generation uses separate fixed contract cases:

```bash
python scripts/eval_local.py --model var/models/Qwen3-0.6B \
  --limit 6 --output reports/generated/local_model
```

It records model outputs, tool plans, model/runtime metadata, source hashes, fallback counts and per-case contract checks. It requires actual local weights and optional dependencies; the default test suite does not run it.

Remote evaluation is opt-in and can incur provider charges:

```bash
# Configure OPS_MODE=llm, LLM_BASE_URL, LLM_API_KEY and LLM_MODEL first
python scripts/eval_live.py --allow-api --limit 8 \
  --output var/live_eval.json
```

A case with `mode=offline_fallback` is not a successful model workflow. Provider usage can be absent; do not infer zero tokens from missing usage. Inspect every failure and fill the human-review fields before making semantic quality claims. The current statistical answer contract preserves the complete tool observation, so results from older source revisions are not directly comparable.

## Interpretation

These authored fixtures are small and share an author with the implementation. High scores can reflect limited coverage and tuning. Quote validity and `answered` do not establish factual correctness. The listed refusal cases do not constitute a comprehensive security evaluation. This repository does not publish a verified production accuracy or remote-provider success rate.

For a more representative evaluation, freeze a separate dataset, annotate relevant evidence and expected answers independently, add ambiguous and adversarial cases, and report model-only success, fallbacks and human judgments separately. Keep dataset and source revisions alongside every report.
