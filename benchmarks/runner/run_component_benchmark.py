#!/usr/bin/env python
"""Component benchmark CLI — STT/LLM/TTS matrix across #68 prompt categories.

Usage:
    python run_component_benchmark.py --config configs/component-benchmark.yaml
    python run_component_benchmark.py --config configs/component-benchmark.yaml --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from component_config import ComponentBenchmarkConfig
from component_runner import ComponentBenchmarkRunner
from upload_loki import push_to_loki

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> int:
    parser = argparse.ArgumentParser(description="TaskOrbit component benchmark runner")
    parser.add_argument("--config", required=True, help="Path to component benchmark YAML")
    parser.add_argument(
        "--results-dir",
        default="benchmarks/results/component",
        help="Directory for JSONL output",
    )
    parser.add_argument("--dry-run", action="store_true", help="Write mock rows without API calls")
    parser.add_argument(
        "--paths",
        default=None,
        help="Comma-separated paths to run (text, voice). Overrides config YAML paths.",
    )
    parser.add_argument("--upload-loki", action="store_true", help="Push results to Loki after run")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config_path = Path(args.config)
    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        return 1

    try:
        config = ComponentBenchmarkConfig.from_yaml(config_path)
        if args.paths:
            config.paths = [p.strip() for p in args.paths.split(",") if p.strip()]
        is_valid, error_msg = config.validate()
        if not is_valid:
            logger.error("Config validation failed: %s", error_msg)
            return 1

        runner = ComponentBenchmarkRunner(results_dir=args.results_dir, dry_run=args.dry_run)
        results_file, summary = await runner.run_experiment(config)
        logger.info("Component benchmark completed: %s", summary)
        logger.info("Results written to %s", results_file)
        
        if args.upload_loki and not args.dry_run:
            loki_url = os.getenv("LOKI_URL", "http://localhost:3100")
            push_to_loki(Path(results_file), config.name, loki_url)
            
        return 0
    except Exception as exc:
        logger.exception("Component benchmark failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
