"""Comparison tool for benchmark runs."""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class BenchmarkComparison:
    """Compare multiple benchmark runs and generate reports."""

    def __init__(self, results_dir: Path | str = "benchmarks/results"):
        """Initialize comparison tool."""
        self.results_dir = Path(results_dir)
        self.index_file = self.results_dir / "index.csv"

    def load_index(self) -> list[dict[str, Any]]:
        """Load index.csv and return all rows."""
        if not self.index_file.exists():
            logger.error(f"Index file not found: {self.index_file}")
            return []

        rows = []
        with open(self.index_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows

    @staticmethod
    def _coerce_int(value: Any, default: int = 0) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _failure_count(self, run: dict[str, Any]) -> int:
        """Derive the number of failed trials from an index row."""
        if run.get("failure_count") not in (None, ""):
            return self._coerce_int(run.get("failure_count"))

        total_trials = self._coerce_int(run.get("total_trials"))
        successes = int(round(total_trials * self._coerce_float(run.get("success_rate"))))
        return max(total_trials - successes, 0)

    def filter_runs(
        self,
        config_name: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Filter runs by config name."""
        rows = self.load_index()

        if config_name:
            rows = [r for r in rows if r.get("config_name") == config_name]

        if limit:
            rows = rows[-limit:]

        return rows

    def generate_csv_comparison(
        self,
        output_file: Path | str,
        config_name: str | None = None,
        limit: int | None = None,
    ) -> None:
        """Generate CSV comparison of runs."""
        runs = self.filter_runs(config_name=config_name, limit=limit)

        if not runs:
            logger.warning("No runs found for comparison")
            return

        output_file = Path(output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        comparison_fields = [
            "run_id",
            "config_name",
            "timestamp",
            "avg_latency_ms",
            "min_latency_ms",
            "max_latency_ms",
            "success_rate",
            "failure_count",
            "total_trials",
            "throughput_avg",
        ]

        with open(output_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=comparison_fields)
            writer.writeheader()
            for run in runs:
                filtered_run = {k: run.get(k, "") for k in comparison_fields}
                filtered_run["failure_count"] = self._failure_count(run)
                writer.writerow(filtered_run)

        logger.info(f"Wrote comparison to {output_file}")

    def generate_text_summary(
        self,
        config_name: str | None = None,
        limit: int | None = 5,
    ) -> str:
        """Generate a text summary of recent runs."""
        runs = self.filter_runs(config_name=config_name, limit=limit)

        if not runs:
            return "No runs found."

        summary_lines = [
            "Benchmark Comparison Summary",
            "=" * 60,
            "",
        ]

        if config_name:
            summary_lines.append(f"Config: {config_name}")
        summary_lines.append(f"Total runs: {len(runs)}")
        summary_lines.append("")

        summary_lines.append(
            f"{'Run ID':<12} {'Avg Latency (ms)':<18} {'Success Rate':<15} {'Failures':<10} {'Trials':<8}"
        )
        summary_lines.append("-" * 60)

        for run in runs:
            run_id = run.get("run_id", "N/A")[:12]
            avg_lat = self._coerce_float(run.get("avg_latency_ms", 0))
            success = self._coerce_float(run.get("success_rate", 0)) * 100
            trials = run.get("total_trials", "N/A")
            failures = self._failure_count(run)

            summary_lines.append(
                f"{run_id:<12} {avg_lat:<18.2f} {success:<14.1f}% {failures:<10} {trials:<8}"
            )

        summary_lines.append("")
        return "\n".join(summary_lines)

    def print_summary(self, config_name: str | None = None, limit: int | None = 5) -> None:
        """Print summary to stdout."""
        print(self.generate_text_summary(config_name=config_name, limit=limit))


def main() -> int:
    """Main entry point for compare CLI."""
    parser = argparse.ArgumentParser(description="Compare benchmark runs")
    parser.add_argument(
        "--config",
        type=str,
        help="Filter by config name",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Limit to N most recent runs (default: 5)",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        help="Output comparison as CSV to this file",
    )
    parser.add_argument(
        "--results-dir",
        type=str,
        default="benchmarks/results",
        help="Results directory (default: benchmarks/results)",
    )

    args = parser.parse_args()

    comparison = BenchmarkComparison(results_dir=args.results_dir)

    if args.output_csv:
        comparison.generate_csv_comparison(
            output_file=args.output_csv,
            config_name=args.config,
            limit=args.limit,
        )
    else:
        comparison.print_summary(config_name=args.config, limit=args.limit)

    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    exit(main())
