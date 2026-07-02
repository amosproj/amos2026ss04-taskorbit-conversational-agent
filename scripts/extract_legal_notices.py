#!/usr/bin/env python3
"""Extract legal-notices.json from a CycloneDX SBOM for the Legal Notices UI.

Reads a CycloneDX JSON v1.5 SBOM (produced by Syft), extracts license
information for every package component, deduplicates, sorts, and writes a
lightweight JSON file consumed by the frontend Legal Notices dialog.

Usage:
  python3 scripts/extract_legal_notices.py \\
    --input Documentation/sbom.cyclonedx.json \\
    --output frontend/src/generated/legal-notices.json

Stdlib only — no external dependencies.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def resolve_license(component: dict[str, Any]) -> str:
    licenses = component.get("licenses")
    if not licenses:
        return "UNKNOWN"
    lic = licenses[0].get("license", {})
    spdx_id = lic.get("id")
    if spdx_id:
        return spdx_id
    name = lic.get("name")
    if name:
        return name
    return "UNKNOWN"


def extract_legal_notices(sbom_path: str) -> dict[str, Any]:
    with open(sbom_path, "r", encoding="utf-8") as f:
        bom = json.load(f)

    components = bom.get("components", [])
    seen: set[tuple[str, str, str]] = set()
    extracted: list[dict[str, Any]] = []

    for comp in components:
        purl = comp.get("purl", "")
        if not purl.startswith("pkg:"):
            continue

        name = comp.get("name", "").lower()
        version = comp.get("version", "")
        ecosystem = comp.get("type", "unknown")
        license_str = resolve_license(comp)

        key = (ecosystem, name, version)
        if key in seen:
            continue
        seen.add(key)

        extracted.append({
            "name": comp.get("name", ""),
            "version": version,
            "license": license_str,
            "ecosystem": ecosystem,
            "purl": purl,
        })

    extracted.sort(key=lambda c: (c["ecosystem"], c["name"].lower(), c["version"]))

    generated_at = bom.get("metadata", {}).get("timestamp", "")
    if not generated_at:
        generated_at = "1970-01-01T00:00:00Z"

    return {
        "generatedAt": generated_at,
        "sbomVersion": "1.5",
        "scope": ["backend", "frontend"],
        "componentCount": len(extracted),
        "components": extracted,
    }


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="Extract legal notices from CycloneDX SBOM"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to CycloneDX JSON input (e.g. Documentation/sbom.cyclonedx.json)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write legal-notices.json (e.g. frontend/src/generated/legal-notices.json)",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.input):
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        return 1

    result = extract_legal_notices(args.input)

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")

    print(f"Legal notices written to {args.output} ({result['componentCount']} components)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
