"""Reproducible, honest small-fixture evaluation; never calls a paid LLM."""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .agent import IncidentAgent, verify_claims
from .paths import resolve_data_dir
from .retrieval import Retriever, ingest
from .storage import Store
from .tools import ToolRegistry


def doc_ranking(hits: list[dict]) -> list[str]:
    return list(dict.fromkeys(hit["doc_id"] for hit in hits))


def retrieval_metrics(ranking: list[str], relevant: list[str], k=3) -> dict:
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    top = ranking[:k]
    labels = set(relevant)
    if not labels:
        raise ValueError("relevant must contain at least one document ID")
    recall = len(set(top) & labels) / len(labels)
    mrr = next((1 / i for i, doc in enumerate(ranking, 1) if doc in labels), 0)
    dcg = sum(1 / math.log2(i + 1) for i, doc in enumerate(top, 1) if doc in labels)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(k, len(labels)) + 1))
    return {"recall_at_3": recall, "mrr": mrr, "ndcg_at_3": dcg / ideal,
            "all_evidence_at_3": float(labels.issubset(top))}


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def evaluate(split="test", output=Path("reports"), semantic=False, data_dir: Path | None = None):
    if split not in {"dev", "test"}:
        raise ValueError("split must be dev or test")
    data = resolve_data_dir(data_dir)
    rows = [json.loads(line) for line in (data / "eval.jsonl").read_text(encoding="utf-8").splitlines()]
    rows = [row for row in rows if row["split"] == split]
    if not rows:
        raise ValueError(f"No evaluation cases for split {split!r} in {data / 'eval.jsonl'}")
    chunks = ingest(data / "knowledge")
    if not chunks:
        raise ValueError(f"No Markdown knowledge found in {data / 'knowledge'}")
    model_path = os.getenv("OPS_EMBED_MODEL") if semantic else None
    if semantic and not model_path:
        raise ValueError("--semantic requires OPS_EMBED_MODEL")
    retriever = Retriever(chunks, model_path, os.getenv("OPS_EMBED_QUERY_PREFIX", ""))
    methods = ["bm25", "tfidf", "hybrid"] + (["semantic"] if semantic else [])
    records, aggregated = [], {}
    for method in methods:
        metrics, durations = [], []
        for row in (r for r in rows if r["kind"] == "retrieval"):
            # Rank enough chunks to deduplicate to distinct documents before applying @3.
            retriever.search(row["question"], len(chunks), method)
            times = []
            for _ in range(5):
                start = time.perf_counter()
                hits = retriever.search(row["question"], len(chunks), method)
                times.append((time.perf_counter() - start) * 1000)
            ranking = doc_ranking(hits)
            scores = retrieval_metrics(ranking, row["relevant_docs"])
            metrics.append(scores)
            durations.append(statistics.median(times))
            records.append({"id": row["id"], "method": method, "question": row["question"],
                            "relevant_docs": row["relevant_docs"], "top3": ranking[:3], **scores})
        if metrics:
            aggregated[method] = {key: round(statistics.mean(m[key] for m in metrics), 4) for key in metrics[0]}
            aggregated[method].update(cases=len(metrics), warm_p50_ms=round(statistics.median(durations), 3),
                                      warm_p95_ms=round(percentile(durations, .95), 3))

    agent_records, latency = [], []
    agent_method = "semantic" if semantic else "bm25"
    with tempfile.TemporaryDirectory() as directory:
        agent = IncidentAgent(ToolRegistry(retriever, data / "logs.csv", agent_method), Store(Path(directory) / "eval.sqlite3"))
        for row in rows:
            start = time.perf_counter()
            result = agent.ask(row["question"])
            elapsed = (time.perf_counter() - start) * 1000
            latency.append(elapsed)
            record = {"id": row["id"], "kind": row["kind"], "question": row["question"],
                      "status": result["status"], "wall_ms": round(elapsed, 3),
                      "citation_quotes_valid": verify_claims(result["claims"], result["evidence"]),
                      "answer": result["answer"]}
            if row["kind"] == "unknown":
                record["correct_refusal"] = result["status"] == "refused"
            if row["kind"] == "tool":
                expected = {"orders-api": {"requests": 100, "http_error_rate": .2, "server_error_rate": .1, "p95_ms": 1980.0},
                            "auth-api": {"requests": 100, "http_error_rate": .05, "server_error_rate": 0.0, "p95_ms": 238.0}}[row["service"]]
                stats = result["log_stats"]
                record["tool_exact_match"] = stats.get("service") == row["service"] and all(stats.get(k) == v for k, v in expected.items())
            agent_records.append(record)
    unknown = [r for r in agent_records if r["kind"] == "unknown"]
    tool_rows = [r for r in agent_records if r["kind"] == "tool"]
    answerable = [r for r in agent_records if r["kind"] != "unknown"]
    answered = [r for r in agent_records if r["status"] == "answered"]
    digest = hashlib.sha256("\n".join(c.id for c in chunks).encode()).hexdigest()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "split": split,
        "mode": "offline_rules_and_extraction", "python": platform.python_version(), "platform": platform.platform(),
        "agent_retrieval_method": agent_method,
        "corpus_sha256": digest, "dataset_sha256": hashlib.sha256((data / "eval.jsonl").read_bytes()).hexdigest(),
        "documents": len({c.doc_id for c in chunks}), "chunks": len(chunks), "cases": len(rows),
        "embedding_model": json.loads((Path(model_path) / "opspilot_manifest.json").read_text()) if model_path and (Path(model_path) / "opspilot_manifest.json").exists() else model_path,
        "retrieval": aggregated,
        "agent": {"correct_refusals": sum(r["correct_refusal"] for r in unknown), "unknown_cases": len(unknown),
                  "tool_exact_matches": sum(r["tool_exact_match"] for r in tool_rows), "tool_cases": len(tool_rows),
                  "false_refusals": sum(r["status"] == "refused" for r in answerable),
                  "answerable_cases": len(answerable), "answered_cases": len(answered),
                  "citation_quote_valid_cases": sum(r["citation_quotes_valid"] for r in answered),
                  "wall_p50_ms": round(statistics.median(latency), 3), "wall_p95_ms": round(percentile(latency, .95), 3)},
        "limitations": ["人工编写的小型合成语料与问题；同一作者可能造成偏差。", "检索指标按不同文档去重，实际Agent最多消费5个chunk。",
                        "未知问题拒答仅覆盖列出的6例，不是全面安全性评测。", "引用校验只检查ID与原文，不验证结论的语义蕴含或事实性。",
                        f"Agent使用{agent_method}检索和规则规划/原文摘录，无真实LLM调用；不代表LLM或生产效果。",
                        "延迟为本机热索引、小规模串行测量，Agent墙钟包含SQLite提交；不含启动和索引构建。"],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{split}_results.json").write_text(json.dumps({"summary": report, "retrieval_cases": records, "agent_cases": agent_records}, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# OpsPilot {split} 评测报告", "", f"语料：{report['documents']} 篇虚构文档 / {len(chunks)} chunks；{len(rows)} 个案例。", "",
             "| 检索方法 | 文档Recall@3 | MRR | nDCG@3 | 全证据命中@3 | 热检索P95(ms) |", "|---|---:|---:|---:|---:|---:|"]
    for method, m in aggregated.items():
        lines.append(f"| {method} | {m['recall_at_3']:.4f} | {m['mrr']:.4f} | {m['ndcg_at_3']:.4f} | {m['all_evidence_at_3']:.4f} | {m['warm_p95_ms']} |")
    a = report["agent"]
    lines += ["", f"离线Agent：工具精确匹配 {a['tool_exact_matches']}/{a['tool_cases']}；未知问题正确拒答 {a['correct_refusals']}/{a['unknown_cases']}；"
              f"可回答问题误拒答 {a['false_refusals']}/{a['answerable_cases']}；已回答样本引用原文校验通过 {a['citation_quote_valid_cases']}/{a['answered_cases']}。",
              "", f"本机端到端P50/P95：{a['wall_p50_ms']} / {a['wall_p95_ms']} ms。", "", "## 失败检索案例", ""]
    failures = [r for r in records if r["all_evidence_at_3"] < 1]
    lines += [f"- {r['method']} / {r['id']}：{r['question']}；预期{r['relevant_docs']}，实际{r['top3']}" for r in failures] or ["- 本组未出现全证据@3失败；样本很小，不代表泛化。"]
    lines += ["", "## 解释边界", ""] + [f"- {v}" for v in report["limitations"]]
    (output / f"{split}_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
