"""Run a fixed small contract benchmark against actual local model weights."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from opspilot.agent import verify_claims
from opspilot.config import build_agent
from opspilot.paths import resolve_data_dir, resolve_state_dir


def main():
    parser = argparse.ArgumentParser(description="真实本地生成模型的小型工作流验收，不调用外部API")
    parser.add_argument("--model", type=Path, default=Path(os.getenv("OPS_LOCAL_MODEL", str(ROOT / "var/models/Qwen3-0.6B"))))
    parser.add_argument("--data-dir", type=Path, help="Knowledge and log directory; honours OPS_DATA_DIR")
    parser.add_argument("--state-dir", type=Path, help="Runtime state directory; honours OPS_STATE_DIR")
    parser.add_argument("--dataset", type=Path, help="JSONL cases; defaults to DATA_DIR/local_model_eval.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/local_model")
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.limit <= 36:
        parser.error("--limit must be between 1 and 36")
    data_dir = resolve_data_dir(args.data_dir)
    dataset = args.dataset or data_dir / "local_model_eval.jsonl"
    cases = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()][:args.limit]
    if not cases:
        parser.error("The dataset contains no cases")
    os.environ.update(OPS_MODE="local", OPS_LOCAL_MODEL=str(args.model), HF_HUB_OFFLINE="1",
                      TRANSFORMERS_OFFLINE="1", HF_HOME=str(ROOT / "var/hf-cache"))
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    agent = build_agent(data_dir=data_dir, state_dir=resolve_state_dir(args.state_dir))
    load_ms = round((time.perf_counter() - started) * 1000, 3)
    source_hash = hashlib.sha256((ROOT / "opspilot/agent.py").read_bytes()).hexdigest()
    records = []
    for case in cases:
        result = agent.ask(case["question"], start_time=case.get("start_time"), end_time=case.get("end_time"))
        plan = next((t for t in result["trace"] if t["node"] == "plan"), {})
        used = {t["name"] for t in result["trace"] if t["node"] == "tool" and t["ok"]}
        planning_pass = plan.get("planner") == "model" and set(case["required_tools"]).issubset(used)
        stats_pass = all(result["log_stats"].get(key) == value for key, value in case.get("expected_stats", {}).items())
        citations_pass = verify_claims(result["claims"], result["evidence"]) if result["status"] == "answered" else None
        cited = {c["source_id"] for c in result["claims"]}
        cited_docs = {e.get("doc_id") for e in result["evidence"] if e["source_id"] in cited}
        statistics_cited = any(source_id.startswith("T:logs:") for source_id in cited) if case.get("expected_stats") else None
        docs_pass = set(case.get("relevant_docs", [])).issubset(cited_docs)
        contract_pass = (result["mode"] == "llm" and planning_pass and stats_pass and docs_pass
                         and result["status"] == case["expected_status"] and citations_pass is not False
                         and statistics_cited is not False)
        record = {"case": case, "checks": {"model_planning_pass": planning_pass, "statistics_exact_match": stats_pass,
                    "citation_quotes_valid": citations_pass, "required_documents_cited": docs_pass,
                    "statistics_evidence_cited": statistics_cited,
                    "expected_status_match": result["status"] == case["expected_status"], "contract_pass": contract_pass},
                  "result": result, "human_review": {"answer_supported_by_evidence": None, "notes": ""}}
        records.append(record)
        # Keep incremental evidence if a later generation is interrupted.
        (args.output / "cases.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{case['id']}: mode={result['mode']} status={result['status']} plan={planning_pass} contract={contract_pass}", flush=True)
    summary = {"created_at": datetime.now(timezone.utc).isoformat(), "model": records[0]["result"].get("model_metadata"),
               "backend": "local_transformers_cpu", "model_load_ms": load_ms,
               "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
               "agent_sha256": source_hash,
               "runtime_sha256": hashlib.sha256((ROOT / "opspilot/local_llm.py").read_bytes()).hexdigest(),
               "versions": {name: importlib.metadata.version(name) for name in ("transformers", "torch", "lm-format-enforcer")},
               "generation": {"device": "cpu", "dtype": "float32", "do_sample": False,
                              "max_new_tokens": int(os.getenv("OPS_LOCAL_MAX_TOKENS", "600")),
                              "json_schema_filter": True},
               "cases": len(records), "model_planning_passes": sum(r["checks"]["model_planning_pass"] for r in records),
               "genuine_model_workflows": sum(r["result"]["mode"] == "llm" for r in records),
               "fallback_cases": sum(r["result"]["mode"] == "offline_fallback" for r in records),
               "contract_passes": sum(r["checks"]["contract_pass"] for r in records),
               "prompt_tokens": sum(r["result"]["usage"].get("prompt_tokens") or 0 for r in records),
               "completion_tokens": sum(r["result"]["usage"].get("completion_tokens") or 0 for r in records),
               "limitations": ["少量固定验收案例，非独立大规模效果评测。", "contract_pass验证工具、数值、状态和引用，不代表语义正确率。",
                               "本地小模型、CPU推理；数据为示例夹具与受控实验。", "人工语义支持审核字段尚未填写。"]}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 真实本地LLM验收报告", "", f"模型：{summary['model']}。本地CPU推理，非Mock，无付费API。", "",
             f"固定案例{len(records)}个，模型工具规划通过{summary['model_planning_passes']}，"
             f"未发生降级的模型工作流{summary['genuine_model_workflows']}，契约验收通过{summary['contract_passes']}，降级{summary['fallback_cases']}。", "",
             "| 案例 | 模式 | 状态 | 模型规划通过 | 契约通过 |", "|---|---|---|---|---|"]
    lines += [f"| {r['case']['id']} | {r['result']['mode']} | {r['result']['status']} | {r['checks']['model_planning_pass']} | {r['checks']['contract_pass']} |" for r in records]
    lines += ["", "## 边界", ""] + ["- " + x for x in summary["limitations"]]
    (args.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
