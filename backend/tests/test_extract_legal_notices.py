"""Unit tests for the CycloneDX → legal-notices.json extraction logic."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add the repo-root scripts directory so extract_legal_notices can be imported
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from extract_legal_notices import extract_legal_notices  # noqa: E402

FIXTURE = _REPO_ROOT / "backend" / "tests" / "fixtures" / "sample.cyclonedx.json"


@pytest.fixture
def result() -> dict:
    return extract_legal_notices(str(FIXTURE))


def test_extracts_spdx_license_id(result: dict) -> None:
    """SPDX license id is used when present."""
    requests = [c for c in result["components"] if c["name"] == "requests"]
    assert len(requests) == 1
    assert requests[0]["license"] == "Apache-2.0"


def test_falls_back_to_license_name(result: dict) -> None:
    """License name is used when no SPDX id is available."""
    flask = [c for c in result["components"] if c["name"] == "Flask"]
    assert len(flask) == 1
    assert flask[0]["license"] == "BSD-3-Clause"


def test_unknown_when_no_license(result: dict) -> None:
    """Packages without license info get UNKNOWN."""
    unknown = [c for c in result["components"] if c["name"] == "unknown-license"]
    assert len(unknown) == 1
    assert unknown[0]["license"] == "UNKNOWN"


def test_dedupes_components(result: dict) -> None:
    """Duplicate ecosystem+name+version are collapsed."""
    flasks = [c for c in result["components"] if c["name"] == "Flask"]
    assert len(flasks) == 1


def test_sorts_alphabetically(result: dict) -> None:
    """Components are sorted by ecosystem, then name, then version."""
    names = [c["name"] for c in result["components"]]
    assert names == sorted(names, key=str.lower)


def test_skips_non_package_components(result: dict) -> None:
    """Components without a pkg: purl are excluded."""
    ubuntu = [c for c in result["components"] if c["name"] == "ubuntu"]
    assert len(ubuntu) == 0


def test_output_schema(result: dict) -> None:
    """Top-level fields match the required schema."""
    assert "generatedAt" in result
    assert "sbomVersion" in result
    assert result["scope"] == ["backend", "frontend"]
    assert "componentCount" in result
    assert isinstance(result["components"], list)
    assert result["componentCount"] == len(result["components"])


def test_component_count_matches(result: dict) -> None:
    """The fixture has 6 pkg: components after dedupe of flask."""
    assert result["componentCount"] == 6
