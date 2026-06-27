"""Aggregator for component benchmark JSONL output — issue #68.

Reads all *.jsonl files from benchmarks/results/component/, produces:
  - benchmarks/results/index.csv   (10 columns consumed by compare.py unchanged)
  - a rich per-config text report with per-stage latency and reliability summary
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reliability import summarize_reliability
from recommendation import format_recommendation_section

logger = logging.getLogger(__name__)

# Latency sub-fields to inspect for the per-stage report.
# Stages that are all-null for a config are silently skipped.
_LATENCY_STAGES = (
    "stt_processing",
    "llm_call",
    "llm_api",
    "tool_call",
    "tts_synthesis",
    "total",
    "voice_turn",
)

# index.csv columns. The first 10 are consumed by compare.py (#86); component
# fields (path + per-stage models) are appended so exports are self-describing.
_INDEX_COLUMNS = [
    "run_id",
    "config_name",
    "path",
    "stt_provider",
    "stt_model",
    "llm_provider",
    "llm_model",
    "tts_provider",
    "tts_model",
    "tts_voice_id",
    "timestamp",
    "avg_latency_ms",
    "min_latency_ms",
    "max_latency_ms",
    "success_rate",
    "failure_count",
    "total_trials",
    "throughput_avg",
]

_SUCCESS_STATUSES: frozenset[str] = frozenset({"success", "ended"})


class BenchmarkAggregator:
    """Aggregate component benchmark JSONL → index.csv + rich component report."""

    def __init__(self, results_dir: Path | str = "benchmarks/results") -> None:
        self.results_dir = Path(results_dir)
        self.component_dir = self.results_dir / "component"
        self.index_file = self.results_dir / "index.csv"

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_jsonl_rows(self) -> list[dict[str, Any]]:
        """Parse every non-empty line from all *.jsonl files in component dir."""
        rows: list[dict[str, Any]] = []
        if not self.component_dir.exists():
            logger.warning("Component results dir not found: %s", self.component_dir)
            return rows
        for path in sorted(self.component_dir.glob("*.jsonl")):
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning("Skipping malformed JSONL line in %s", path)
        return rows

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _latency_totals(rows: list[dict[str, Any]]) -> list[float]:
        """Return non-null latency_ms.total values from a group of rows."""
        result = []
        for row in rows:
            v = (row.get("latency_ms") or {}).get("total")
            if v is not None:
                try:
                    result.append(float(v))
                except (TypeError, ValueError):
                    pass
        return result

    # ------------------------------------------------------------------
    # index.csv
    # ------------------------------------------------------------------

    @staticmethod
    def _config_index_fields(row: dict[str, Any]) -> dict[str, str]:
        """Extract pipeline provider/model identifiers for index.csv."""
        cfg = row.get("config") or {}
        return {
            "path": str(row.get("path", "text")),
            "stt_provider": str(cfg.get("stt_provider", "")),
            "stt_model": str(cfg.get("stt_model", "")),
            "llm_provider": str(cfg.get("llm_provider", "")),
            "llm_model": str(cfg.get("llm_model", "")),
            "tts_provider": str(cfg.get("tts_provider", "")),
            "tts_model": str(cfg.get("tts_model", "")),
            "tts_voice_id": str(cfg.get("tts_voice_id", "")),
        }

    def _aggregate_group(
        self,
        rows: list[dict[str, Any]],
        run_id: str,
        config_label: str,
        path: str,
    ) -> dict[str, Any]:
        """Compute index.csv fields for one (run_id, config_label, path) group."""
        totals = self._latency_totals(rows)

        success_count = sum(1 for r in rows if r.get("status") in _SUCCESS_STATUSES)
        total_trials = len(rows)
        failure_count = total_trials - success_count
        success_rate = success_count / total_trials if total_trials else 0.0

        avg_lat = statistics.mean(totals) if totals else 0.0
        min_lat = min(totals) if totals else 0.0
        max_lat = max(totals) if totals else 0.0

        # throughput: successful responses per second of observed total latency.
        # Denominator = sum(non-null latency_ms.total) / 1000 → seconds.
        # Error rows whose total is null are excluded from the denominator so
        # they do not artificially inflate apparent throughput.
        total_latency_s = sum(totals) / 1000.0
        throughput_avg = success_count / total_latency_s if total_latency_s > 0 else 0.0

        timestamp = rows[0].get("timestamp", "") if rows else ""

        result: dict[str, Any] = {
            "run_id": run_id,
            "config_name": config_label,
            "timestamp": timestamp,
            "avg_latency_ms": round(avg_lat, 4),
            "min_latency_ms": round(min_lat, 4),
            "max_latency_ms": round(max_lat, 4),
            "success_rate": round(success_rate, 6),
            "failure_count": failure_count,
            "total_trials": total_trials,
            "throughput_avg": round(throughput_avg, 6),
        }
        if rows:
            result.update(self._config_index_fields(rows[0]))
        else:
            result["path"] = path
        return result

    def write_index_csv(
        self, rows: list[dict[str, Any]] | None = None
    ) -> Path:
        """Read JSONL, aggregate per (run_id, config_label, path), write index.csv.

        Text and voice path rows are written as separate index rows so latency
        averages are never mixed across paths.
        """
        if rows is None:
            rows = self.load_jsonl_rows()

        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            key = (
                row.get("run_id") or "unknown",
                row.get("config_label") or "unknown",
                row.get("path", "text"),
            )
            groups.setdefault(key, []).append(row)

        index_rows = [
            self._aggregate_group(group_rows, run_id, config_label, path)
            for (run_id, config_label, path), group_rows in sorted(groups.items())
        ]

        self.results_dir.mkdir(parents=True, exist_ok=True)
        with open(self.index_file, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=_INDEX_COLUMNS)
            writer.writeheader()
            for idx_row in index_rows:
                writer.writerow({k: idx_row.get(k, "") for k in _INDEX_COLUMNS})

        logger.info(
            "Wrote %d row(s) to index.csv → %s", len(index_rows), self.index_file
        )
        return self.index_file

    # ------------------------------------------------------------------
    # Component report
    # ------------------------------------------------------------------

    def generate_component_report(
        self, rows: list[dict[str, Any]] | None = None
    ) -> str:
        """Return a rich per-config text report.

        Shows per-stage latency averages, per-category breakdown, and an
        authoritative reliability summary per (config_label, category).
        Text and voice path rows are kept in separate sections.
        """
        if rows is None:
            rows = self.load_jsonl_rows()

        text_rows = [r for r in rows if r.get("path", "text") == "text"]
        voice_rows = [r for r in rows if r.get("path") == "voice"]

        lines: list[str] = [
            "Component Benchmark Report",
            "=" * 60,
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "",
        ]

        for path_label, path_rows in (("text", text_rows), ("voice", voice_rows)):
            if not path_rows:
                continue
            lines.append(f"Path: {path_label}")
            lines.append("-" * 60)
            lines.append("")
            lines.extend(self._build_report_section(path_rows))

        return "\n".join(lines)

    def _build_report_section(self, rows: list[dict[str, Any]]) -> list[str]:
        """Report lines for one path type, one block per config_label."""
        by_config: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            label = row.get("config_label") or "unknown"
            by_config.setdefault(label, []).append(row)

        lines: list[str] = []
        for config_label, config_rows in sorted(by_config.items()):
            lines.append(f"Config: {config_label}  ({len(config_rows)} rows)")
            cfg = (config_rows[0].get("config") or {}) if config_rows else {}
            if cfg:
                lines.append(
                    "  Pipeline:"
                    f" STT {cfg.get('stt_provider', '?')}/{cfg.get('stt_model', '?')}"
                    f" | LLM {cfg.get('llm_provider', '?')}/{cfg.get('llm_model', '?')}"
                    f" | TTS {cfg.get('tts_provider', '?')}/{cfg.get('tts_model', '?')}"
                )

            # Per-stage latency averages; skip stages where every value is null.
            lines.append("  Stage Latency Averages (ms):")
            any_stage = False
            for stage in _LATENCY_STAGES:
                values: list[float] = []
                for r in config_rows:
                    v = (r.get("latency_ms") or {}).get(stage)
                    if v is not None:
                        try:
                            values.append(float(v))
                        except (TypeError, ValueError):
                            pass
                if values:
                    lines.append(f"    {stage:<22} {statistics.mean(values):.1f}")
                    any_stage = True
            if not any_stage:
                lines.append("    (no latency data)")

            # Per prompt.category breakdown.
            lines.append("  By Category:")
            by_cat: dict[str, list[dict[str, Any]]] = {}
            for row in config_rows:
                cat = (row.get("prompt") or {}).get("category") or "unknown"
                by_cat.setdefault(cat, []).append(row)

            for cat, cat_rows in sorted(by_cat.items()):
                n_success = sum(1 for r in cat_rows if r.get("status") in _SUCCESS_STATUSES)
                totals = self._latency_totals(cat_rows)
                avg_str = f"{statistics.mean(totals):.1f} ms avg" if totals else "no latency data"
                lines.append(
                    f"    {cat:<28} {len(cat_rows):>3} rows  "
                    f"{n_success}/{len(cat_rows)} success  {avg_str}"
                )

            # Authoritative reliability summary from reliability.py.
            lines.append("  Reliability (authoritative):")
            rel = summarize_reliability(config_rows)
            if rel:
                for _key, stats in sorted(rel.items()):
                    rate_pct = stats["reliability_rate"] * 100
                    lines.append(
                        f"    {stats['category']:<28} "
                        f"{stats['pass']:>3} / {stats['total']:<3} pass  "
                        f"reliability_rate: {rate_pct:.1f}%"
                    )
            else:
                lines.append("    (no data)")

            lines.append("")

        return lines

    def generate_full_report(
        self, rows: list[dict[str, Any]] | None = None, *, include_recommendation: bool = True
    ) -> str:
        """Component report plus optional default-config recommendation per path."""
        if rows is None:
            rows = self.load_jsonl_rows()
        parts = [self.generate_component_report(rows)]
        if include_recommendation:
            for path in ("text", "voice"):
                path_rows = [r for r in rows if r.get("path", "text") == path]
                if path_rows:
                    parts.append("")
                    parts.append(format_recommendation_section(rows, path=path))
        return "\n".join(parts)

    def print_report(
        self, rows: list[dict[str, Any]] | None = None, *, include_recommendation: bool = True
    ) -> None:
        """Print the component report to stdout."""
        print(self.generate_full_report(rows, include_recommendation=include_recommendation))


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def main() -> int:
    """CLI entry point: aggregate JSONL → index.csv, optionally print report."""
    parser = argparse.ArgumentParser(
        description="Aggregate component benchmark JSONL → index.csv + report"
    )
    parser.add_argument(
        "--results-dir",
        type=str,
        default="benchmarks/results",
        help="Results directory containing component/ subdir (default: benchmarks/results)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print the per-config component report to stdout",
    )
    parser.add_argument(
        "--no-index",
        action="store_true",
        help="Skip writing index.csv (useful when only --report is needed)",
    )
    parser.add_argument(
        "--recommend",
        action="store_true",
        help="Print default configuration recommendation (included in --report)",
    )
    parser.add_argument(
        "--write-report",
        type=str,
        metavar="PATH",
        help="Write full report (with recommendation) to a markdown/text file",
    )
    args = parser.parse_args()

    aggregator = BenchmarkAggregator(results_dir=args.results_dir)
    rows = aggregator.load_jsonl_rows()

    if not args.no_index:
        index_path = aggregator.write_index_csv(rows)
        print(f"Wrote index.csv → {index_path}")

    if args.report or args.recommend:
        aggregator.print_report(rows, include_recommendation=True)

    if args.write_report:
        report_path = Path(args.write_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(aggregator.generate_full_report(rows), encoding="utf-8")
        print(f"Wrote report → {report_path}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    exit(main())
