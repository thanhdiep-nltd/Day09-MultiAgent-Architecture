from __future__ import annotations

import argparse
import json
import sys
import io
from pathlib import Path

# Fix Windows encoding issue when printing Vietnamese characters
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from app.graph import ShoppingAssistant


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Student scaffold CLI.")
    parser.add_argument("--question", help="Run one question through the graph.")
    parser.add_argument("--test-file", default="data/test.json")
    parser.add_argument("--trace-file", default=None)
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--output-dir", default="src/artifacts/batch_results")
    parser.add_argument("--rebuild-index", action="store_true", help="Rebuild vector store index from scratch")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    assistant = ShoppingAssistant()

    if args.batch:
        print(f"Running batch tests from {args.test_file}...")
        test_file_path = Path(args.test_file)
        output_dir_path = Path(args.output_dir)
        summary = assistant.run_batch(
            test_file=test_file_path,
            output_dir=output_dir_path,
            rebuild_index=args.rebuild_index,
        )
        print("\n=== Batch Test Summary ===")
        print(f"Total Cases:  {summary['total_cases']}")
        print(f"Passed Cases: {summary['passed_cases']}")
        print(f"Pass Rate:    {summary['pass_rate'] * 100:.2f}%")
        print(f"Results saved in: {output_dir_path}")
    elif args.question:
        print(f"Running question: '{args.question}'...")
        trace_path = Path(args.trace_file) if args.trace_file else None
        res = assistant.ask(
            question=args.question,
            trace_file=trace_path,
            rebuild_index=args.rebuild_index,
        )
        print("\n=== Final Answer ===")
        print(res["final_answer"])
        if trace_path:
            print(f"\nTrace saved to: {trace_path}")
    else:
        print("Please provide either --question or --batch. Use --help for usage details.")


if __name__ == "__main__":
    main()
