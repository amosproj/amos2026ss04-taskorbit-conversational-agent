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


def ecosystem_from_purl(purl: str | None) -> str:
    """Derive a simple ecosystem string from a package URL (purl).

    Examples:
      pkg:pypi/requests@2.31.0  -> python
      pkg:npm/react@18.3.0      -> npm
    """
    if not purl:
        return "unknown"
    if not purl.startswith("pkg:"):
        return "unknown"
    rest = purl[4:]
    type_part = rest.split("/", 1)[0]
    mapping = {
        "pypi": "python",
        "npm": "npm",
        "gem": "ruby",
        "maven": "maven",
        "golang": "go",
        "golang-module": "go",
        "cargo": "rust",
        "composer": "php",
        "nuget": "dotnet",
        "deb": "debian",
        "rpm": "rpm",
        "docker": "docker",
    }
    return mapping.get(type_part, type_part or "other")


def resolve_license(component: dict[str, Any]) -> str:
    """Return a human-readable license string for a CycloneDX component.

    Handles these common shapes produced by Syft / CycloneDX:
      - {"licenses": [{"license": {"id": "SPDX"}}]}
      - {"licenses": [{"license": {"name": "License Name"}}]}
      - {"licenses": [{"expression": "Apache-2.0 AND BSD-3-Clause"}]}
    """
    licenses = component.get("licenses")
    if not licenses:
        return "UNKNOWN"
    first = licenses[0]

    # CycloneDX 1.5 may express complex expressions directly on the license entry.
    if isinstance(first, dict) and first.get("expression"):
        expr = first.get("expression")
        return expr if expr else "UNKNOWN"

    # Normalized license object may appear under the 'license' key.
    lic = None
    if isinstance(first, dict) and "license" in first:
        lic = first.get("license") or {}
    elif isinstance(first, dict):
        lic = first
    else:
        lic = {}

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
        ecosystem = ecosystem_from_purl(purl)
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
