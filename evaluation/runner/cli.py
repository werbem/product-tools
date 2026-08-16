"""Command line entrypoint for the evaluation runner."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from evaluation.runner.case_loader import load_cases
from evaluation.runner.runner import EvaluationRunner
from evaluation.scorer.scorer import score_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MCP benchmark cases")
    parser.add_argument(
        "--case",
        default=None,
        help="Run a single case_id, for example case_001",
    )
    parser.add_argument(
        "--case-dir",
        default="evaluation/cases",
        help="Directory containing benchmark JSON cases",
    )
    parser.add_argument(
        "--result-dir",
        default="evaluation/results",
        help="Directory for persisted results",
    )
    parser.add_argument(
        "--score",
        action="store_true",
        help="Run rule-based scoring after benchmark execution",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate evaluation report from score_report.json",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        default=None,
        metavar=("BASELINE", "CURRENT"),
        help="Compare two score_report.json files",
    )
    return parser


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    case_dir = Path(args.case_dir)
    result_dir = Path(args.result_dir)

    if args.report:
        from evaluation.reports.markdown_renderer import render_markdown_file
        from evaluation.reports.report_generator import generate_report

        score_path = result_dir / "score_report.json"
        report_path = Path("evaluation/reports/report.json")
        markdown_path = Path("evaluation/reports/report.md")
        generate_report(score_path, report_path)
        render_markdown_file(report_path, markdown_path)
        print(f"report: {report_path}")
        print(f"markdown: {markdown_path}")
        return 0

    if args.compare:
        from evaluation.comparison.baseline import load_score_report
        from evaluation.comparison.regression import compare_score_reports

        baseline = load_score_report(Path(args.compare[0]))
        current = load_score_report(Path(args.compare[1]))
        comparison = compare_score_reports(baseline, current)
        output_path = Path("evaluation/comparison/regression_report.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"regression report: {output_path}")
        print(f"overall score delta: {comparison['overall_score']['delta']}")
        return 0

    if args.case:
        case = next(
            (c for c in load_cases(case_dir) if c["case_id"] == args.case),
            None,
        )
        if case is None:
            print(f"case not found: {args.case}")
            return 1
        results = [await EvaluationRunner(case_dir, result_dir).run_case(case)]
    else:
        results = await EvaluationRunner(case_dir, result_dir).run_all()

    for result in results:
        print(
            f"{result['case_id']}: {result['status']} "
            f"({result['execution_time']}ms)"
        )

    if args.score:
        cases = (
            [case]
            if args.case
            else load_cases(case_dir)
        )
        report = score_report(cases, results)
        report_path = result_dir / "score_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"score report: {report_path}")
        print(f"average score: {report['average_score']}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))
