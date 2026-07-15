#!/usr/bin/env python
import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import httpx
except ImportError:
    print("httpx is required. Please install it using `pip install httpx`.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def push_to_loki(jsonl_path: Path, config_name: str, loki_url: str) -> None:
    """Read a JSONL file and push its contents to Loki as structured logs."""
    if not jsonl_path.exists():
        logger.error(f"Results file not found: {jsonl_path}")
        return

    push_url = f"{loki_url.rstrip('/')}/loki/api/v1/push"
    values = []

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            try:
                data = json.loads(line)
                # Parse timestamp to nanoseconds
                ts_str = data.get("timestamp", datetime.utcnow().isoformat() + "Z")
                ts_str = ts_str.replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts_str)
                ns_timestamp = str(int(dt.timestamp() * 1e9))
                
                # Push the full JSON as the log line body
                values.append([ns_timestamp, line])
            except Exception as e:
                logger.warning(f"Skipping invalid JSON line: {e}")

    if not values:
        logger.warning("No valid rows found to push to Loki.")
        return

    payload = {
        "streams": [
            {
                "stream": {
                    "job": "benchmark",
                    "config": config_name
                },
                "values": values
            }
        ]
    }

    try:
        response = httpx.post(push_url, json=payload, timeout=10.0)
        response.raise_for_status()
        logger.info(f"Successfully pushed {len(values)} benchmark records to Loki at {loki_url}")
    except Exception as e:
        logger.error(f"Failed to push metrics to Loki: {e}")
        if isinstance(e, httpx.HTTPStatusError):
            logger.error(f"Loki response: {e.response.text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload benchmark results to Loki")
    parser.add_argument("--file", required=True, help="Path to results.jsonl")
    parser.add_argument("--config", required=True, help="Name of the config/experiment")
    parser.add_argument("--url", default=os.getenv("LOKI_URL", "http://localhost:3100"), help="Loki API URL")
    
    args = parser.parse_args()
    push_to_loki(Path(args.file), args.config, args.url)
