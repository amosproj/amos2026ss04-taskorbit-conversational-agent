#!/usr/bin/env python3
"""Validate agent configuration files for basic guardrail presence.

Current checks (non-exhaustive):
- frontend/src/lib/mockAgents.ts must contain the string 'persona_constraints'

This script is intentionally lightweight: it fails fast when a front-end demo
agent lacks guardrails and exits non-zero so CI can surface the issue.

Future improvements:
- Validate backend seed_data entries (optionally, behind a flag)
- Validate only changed files in pull requests
- Provide autofix scaffolding suggestions
"""
from __future__ import annotations

import argparse
import os
import sys


def check_mock_agents(repo_root: str) -> int:
    path = os.path.join(repo_root, "frontend", "src", "lib", "mockAgents.ts")
    if not os.path.exists(path):
        print(f"ERROR: mockAgents file not found: {path}", file=sys.stderr)
        return 2
    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read()
    if "persona_constraints" not in content:
        print("ERROR: 'persona_constraints' not found in frontend/mockAgents.ts", file=sys.stderr)
        return 1
    print("OK: frontend/mockAgents.ts contains persona_constraints")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    parser = argparse.ArgumentParser(description="Validate agent configs for guardrails")
    parser.add_argument("--repo-root", default=os.path.dirname(os.path.dirname(__file__)), help="Repository root (default: parent of scripts/)")
    parser.add_argument("--check-seed", action="store_true", help="(Optional) run seed_data checks too — currently disabled by default")
    args = parser.parse_args(argv)

    repo_root = os.path.abspath(args.repo_root)

    # 1. Quick front-end mockAgents check (covers most demo agent cases)
    rc = check_mock_agents(repo_root)
    if rc != 0:
        return rc

    # TODO: implement seed_data checks behind --check-seed
    if args.check_seed:
        print("Seed checks not yet implemented", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
