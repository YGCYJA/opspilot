from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import build_agent
from .paths import resolve_data_dir, resolve_state_dir
from .retrieval import ingest, save_index


def main():
    parser = argparse.ArgumentParser(description="OpsPilot 知识库与故障诊断 Agent")
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask")
    ask.add_argument("question")
    ask.add_argument("--session", default=None)
    ask.add_argument("--json", action="store_true")
    ask.add_argument("--start-time", default=None)
    ask.add_argument("--end-time", default=None)
    index = sub.add_parser("ingest")
    index.add_argument("--directory", type=Path, default=None,
                       help="Markdown directory (default: resolved data directory / knowledge)")
    index.add_argument("--output", type=Path, default=None,
                       help="Index file (default: OPS_STATE_DIR/index.json or ./var/index.json)")
    evaluate = sub.add_parser("eval")
    evaluate.add_argument("--split", choices=["dev", "test"], default="test")
    evaluate.add_argument("--output", type=Path, default=Path("reports"))
    evaluate.add_argument("--semantic", action="store_true")
    args = parser.parse_args()
    if args.command == "ingest":
        directory = args.directory if args.directory is not None else resolve_data_dir() / "knowledge"
        output = args.output if args.output is not None else resolve_state_dir() / "index.json"
        chunks = ingest(directory)
        if not chunks:
            parser.error(f"No Markdown knowledge found in {directory}")
        save_index(chunks, output)
        print(f"Indexed {len(chunks)} chunks from {len({c.doc_id for c in chunks})} documents -> {output}")
    elif args.command == "eval":
        from .evaluate import evaluate
        print(json.dumps(evaluate(args.split, args.output, args.semantic), ensure_ascii=False, indent=2))
    else:
        result = build_agent().ask(args.question, args.session, start_time=args.start_time, end_time=args.end_time)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"mode={result['mode']} status={result['status']} latency={result['latency_ms']}ms")
            print(result["answer"])
            for warning in result["warnings"]:
                print("提示：" + warning)
            print(f"run_id={result['run_id']} session_id={result['session_id']}")


if __name__ == "__main__":
    main()
