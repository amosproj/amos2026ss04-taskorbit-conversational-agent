#!/usr/bin/env python
"""Benchmark runner CLI — main entry point.

Usage:
    python run_benchmark.py --config benchmarks/configs/baseline-cloud.yaml
    python run_benchmark.py --config benchmarks/configs/baseline-cloud.yaml --dry-run
    python run_benchmark.py --config benchmarks/configs/baseline-cloud.yaml --upload-metrics
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

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

        runner = BenchmarkRunner(
            results_dir=args.results_dir,
            dry_run=args.dry_run,
        )

        run_id, results_file, summary = await runner.run_experiment(config)

        logger.info(f"Experiment completed: run_id={run_id}")
        logger.info(f"Results: {results_file}")
        logger.info(f"Summary: {summary}")

        if args.upload_metrics:
            logger.info("Upload to OpenTelemetry: feature not yet implemented")

        return 0

    except Exception as e:
        logger.exception(f"Benchmark runner failed: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
