#!/usr/bin/env python
"""Benchmark runner CLI — main entry point.

Usage:
    python run_benchmark.py --config benchmarks/configs/experiment-1.yaml
    python run_benchmark.py --config benchmarks/configs/experiment-1.yaml --dry-run
    python run_benchmark.py --config benchmarks/configs/experiment-1.yaml --upload-metrics
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from config import ExperimentConfig
from runner import BenchmarkRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="TaskOrbit benchmark runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to experiment config (YAML)",
    )
    parser.add_argument(
        "--results-dir",
        type=str,
        default="benchmarks/results",
        help="Directory to store results (default: benchmarks/results)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate experiment without executing trials",
    )
    parser.add_argument(
        "--upload-metrics",
        action="store_true",
        help="Push metrics to OpenTelemetry endpoint after run",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        return 1

    try:
        logger.info(f"Loading config from {config_path}")
        config = ExperimentConfig.from_yaml(config_path)

        is_valid, error_msg = config.validate()
        if not is_valid:
            logger.error(f"Config validation failed: {error_msg}")
            return 1

        logger.info(f"Config valid: {config.name}")

        input_data = _load_input_data(config.input_set)

        runner = BenchmarkRunner(
            results_dir=args.results_dir,
            dry_run=args.dry_run,
        )

        run_id, results_file, summary = await runner.run_experiment(config, input_data=input_data)

        logger.info(f"Experiment completed: run_id={run_id}")
        logger.info(f"Results: {results_file}")
        logger.info(f"Summary: {summary}")

        if args.upload_metrics:
            from metrics import export_to_otel
            exported = export_to_otel(run_id=run_id, config_name=config.name, summary=summary)
            if not exported:
                logger.warning("OTel export skipped — set OTEL_EXPORTER_OTLP_ENDPOINT to enable")

        return 0

    except Exception as e:
        logger.exception(f"Benchmark runner failed: {e}")
        return 1


def _load_input_data(input_set: str) -> list[dict[str, Any]]:
    """Load prompts from a JSONL file. Returns empty list if file not found."""
    path = Path(input_set)
    if not path.exists():
        logger.warning(f"Input set not found: {path} — trials will use a default prompt")
        return []
    rows: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    logger.info(f"Loaded {len(rows)} prompts from {path}")
    return rows


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
