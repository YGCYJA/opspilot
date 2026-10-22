from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import model_factory_from_env
from .triage import analyze_failure, render_report


def main():
    parser = argparse.ArgumentParser(description='OpsPilot：分析本地 pytest 失败、关联改动并整理证据')
    commands = parser.add_subparsers(dest='command', required=True)
    triage = commands.add_parser('triage', help='Read a JUnit report and local project without executing project code')
    triage.add_argument('--repo', type=Path, required=True, help='Existing local Python project directory')
    triage.add_argument('--junit', type=Path, required=True, help='pytest --junitxml report')
    triage.add_argument('--base', dest='base_ref', help='Explicit local Git base ref; HEAD compares committed baseline with working tree')
    triage.add_argument('--notes', type=Path, help='Markdown project rules directory, inside the analyzed repository')
    triage.add_argument('--output', type=Path, help='Directory for report.json and report.md')
    triage.add_argument('--json', action='store_true', help='Print JSON instead of Markdown')
    triage.add_argument('--offline', action='store_true', help='Skip optional model even if OPS_MODE is configured')
    args = parser.parse_args()
    try:
        factory = model_factory_from_env(args.offline)
    except ValueError as error:
        parser.error(str(error))
    result = analyze_failure(args.repo, args.junit, args.base_ref, args.notes, factory)
    report = render_report(result)
    if args.output:
        try:
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            (args.output / 'report.md').write_text(report, encoding='utf-8')
        except OSError:
            parser.exit(2, 'Could not write output directory; choose a writable location.\n')
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else report)
    if result['status'] == 'invalid_input':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
