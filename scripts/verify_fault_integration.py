"""Connect actual fault-lab CSVs to the production code path without fabricating logs."""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from opspilot.agent import IncidentAgent, verify_claims
from opspilot.retrieval import Retriever, ingest
from opspilot.storage import Store
from opspilot.tools import ToolRegistry


def main():
    parser = argparse.ArgumentParser(description="将实际本地故障实验结果接入时间统计与Agent链路并验收")
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/fault_lab")
    parser.add_argument("--state-dir", type=Path, default=ROOT / "var/fault_integration")
    args = parser.parse_args()
    summaries = sorted((ROOT / "var/fault_lab").glob("*/summary.json"))
    source = args.summary or (summaries[-1] if summaries else None)
    if source is None:
        parser.error("Run scripts/run_fault_lab.py first, or provide --summary")
    summary = json.loads(source.read_text(encoding="utf-8"))
    if args.output.resolve() == source.parent.resolve():
        parser.error("--output must differ from the source run directory to preserve raw evidence")
    logs = source.parent / "logs.csv"
    agent = IncidentAgent(ToolRegistry(Retriever(ingest(ROOT / "data/knowledge")), logs),
                          Store(args.state_dir / "runs.sqlite3"))
    results = []
    for scenario in summary["scenarios"]:
        bounds = scenario["query_arguments"]
        result = agent.ask("统计orders-api日志的请求数、HTTP错误率和P95延迟，说明数据来源。",
                           start_time=bounds["start_time"], end_time=bounds["end_time"])
        expected = {key: scenario[key] for key in ("requests", "status_counts", "http_error_rate", "p95_ms")}
        matched = all(result["log_stats"].get(key) == value for key, value in expected.items())
        matched = matched and result["log_stats"].get("data_kind") == "local_fault_injection"
        citations = verify_claims(result["claims"], result["evidence"])
        results.append({"scenario": scenario["scenario"], "statistics_exact_match": matched,
                        "citation_quotes_valid": citations, "client_timeout_count": scenario["client_timeout_count"],
                        "result": result})
    args.output.mkdir(parents=True, exist_ok=True)
    for filename in ("logs.csv", "client_observations.json", "report.md"):
        shutil.copy2(source.parent / filename, args.output / filename)
    portable_summary = {**summary, "artifacts": {name: name for name in
                        ("logs.csv", "client_observations.json", "summary.json", "report.md")}}
    (args.output / "summary.json").write_text(json.dumps(portable_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {"source_run_id": summary["run_id"], "data_kind": summary["data_kind"],
                "actual_http_requests": summary["client_requests"], "cases": len(results),
                "statistics_exact_matches": sum(r["statistics_exact_match"] for r in results),
                "citation_quote_valid_cases": sum(r["citation_quotes_valid"] for r in results),
                "source_sha256": {filename: hashlib.sha256((source.parent / filename).read_bytes()).hexdigest()
                                  for filename in ("logs.csv", "client_observations.json", "summary.json")},
                "exported_sha256": {filename: hashlib.sha256((args.output / filename).read_bytes()).hexdigest()
                                    for filename in ("logs.csv", "client_observations.json", "summary.json")},
                "results": results}
    (args.output / "integration.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 本地故障实验 → 时间统计 → Agent 集成验收", "",
             f"实际HTTP请求：{summary['client_requests']}；统计精确匹配：{manifest['statistics_exact_matches']}/{len(results)}；"
             f"引用原文校验通过：{manifest['citation_quote_valid_cases']}/{len(results)}。", "",
             "| 场景 | 窗口统计匹配 | 请求数 | HTTP错误率 | P95(ms) | 客户端超时数 |",
             "|---|---|---:|---:|---:|---:|"]
    for row in results:
        stats = row["result"]["log_stats"]
        lines.append(f"| {row['scenario']} | {row['statistics_exact_match']} | {stats['requests']} | {stats['http_error_rate']} | {stats['p95_ms']} | {row['client_timeout_count']} |")
    lines += ["", "这项验收使用真实本地HTTP所生成的原始日志；故障是实验主动注入，不是企业生产事故。",
              "Agent部分使用规则规划与原文摘录，真实生成模型的验收另见local_model报告。",
              "客户端超时与服务端最终200可以同时发生，不能把两类观测合并为一个HTTP状态。"]
    (args.output / "integration.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in manifest.items() if key != "results"}, ensure_ascii=False, indent=2))
    if not all(r["statistics_exact_match"] and r["citation_quotes_valid"] for r in results):
        raise SystemExit("Fault lab integration failed; inspect integration.json")


if __name__ == "__main__":
    main()
