"""Run local fault injection; every generated result comes from real local HTTP."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opspilot.fault_lab import run_experiment


def main():
    parser = argparse.ArgumentParser(description="用真实 loopback HTTP 请求运行本地受控故障实验")
    parser.add_argument("--output-dir", type=Path, default=Path("var/fault_lab"))
    parser.add_argument("--requests-per-scenario", type=int, default=5)
    parser.add_argument("--port", type=int, default=0, help="默认 0：由系统分配空闲本地端口")
    args = parser.parse_args()
    if not 1 <= args.requests_per_scenario <= 100:
        parser.error("--requests-per-scenario 必须在 1 到 100 之间")
    if not 0 <= args.port <= 65535:
        parser.error("--port 必须在 0 到 65535 之间")
    summary = run_experiment(args.output_dir, args.requests_per_scenario, args.port)
    print(json.dumps({"run_id": summary["run_id"], "data_kind": summary["data_kind"],
                      "server_requests": summary["server_requests"], "artifacts": summary["artifacts"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
