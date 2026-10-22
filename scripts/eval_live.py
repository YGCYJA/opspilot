"""Opt-in provider evaluation with records for subsequent human review."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from opspilot.config import build_agent
from opspilot.paths import resolve_data_dir


def main():
    parser = argparse.ArgumentParser(description="Evaluate your configured real model, with explicit API opt-in")
    parser.add_argument("--allow-api", action="store_true", help="Acknowledge that configured model requests may incur charges")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--data-dir", type=Path, help="Knowledge, logs and evaluation data directory")
    parser.add_argument("--dataset", type=Path, help="JSONL cases; defaults to DATA_DIR/eval.jsonl")
    parser.add_argument("--output", type=Path, default=Path("var/live_eval.json"))
    args = parser.parse_args()
    if not args.allow_api or os.getenv("OPS_MODE") != "llm":
        parser.error("Set OPS_MODE=llm and explicitly pass --allow-api")
    if not 1 <= args.limit <= 36:
        parser.error("--limit must be between 1 and 36")
    data_dir = resolve_data_dir(args.data_dir)
    dataset = args.dataset or data_dir / "eval.jsonl"
    rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    # Interleave task types so the default eight cases cover retrieval, tools and refusal.
    groups = [[r for r in rows if r["split"] == "test" and r["kind"] == kind] for kind in ("retrieval", "tool", "unknown")]
    selected = [g[i] for i in range(max(map(len, groups))) for g in groups if i < len(g)][:args.limit]
    if not selected:
        parser.error("The dataset contains no test cases of kind retrieval, tool or unknown")
    agent = build_agent(data_dir=data_dir)
    records = []
    for row in selected:
        result = agent.ask(row["question"], start_time=row.get("start_time"), end_time=row.get("end_time"))
        records.append({"case": row, "result": result, "human_review": {
            "answer_supported_by_evidence": None, "all_required_evidence_used": None, "notes": ""}})
        print(f"{row['id']} mode={result['mode']} status={result['status']} calls={result['model_calls']}")
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "model": os.getenv("LLM_MODEL"),
              "cases": len(records), "genuine_llm_cases": sum(r["result"]["mode"] == "llm" for r in records),
              "fallback_cases": sum(r["result"]["mode"] == "offline_fallback" for r in records),
              "note": "人工语义支持审核尚未填写；不可把answered状态或引用存在解释为事实正确。", "records": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {args.output}; review human_review fields before claiming model quality")


if __name__ == "__main__":
    main()
