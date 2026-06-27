"""Default pipeline configuration recommendation — issue #68.

Primary criterion: lowest average end-to-end latency (latency_ms.total).
Secondary criterion: highest tool-call reliability rate when latencies are
within ``LATENCY_TIE_THRESHOLD`` of each other.
"""

from __future__ import annotations

import statistics
from typing import Any

from reliability import evaluate_reliability_authoritative

LATENCY_TIE_THRESHOLD = 0.10  # 10 % — configs within this band tie-break on reliability


def _config_stats(rows: list[dict[str, Any]], *, path: str) -> dict[str, dict[str, Any]]:
    """Aggregate latency + reliability per config_label for one path."""
    by_config: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("path", "text") != path:
            continue
        label = row.get("config_label") or "unknown"
        by_config.setdefault(label, []).append(row)

    stats: dict[str, dict[str, Any]] = {}
    for label, config_rows in by_config.items():
        totals: list[float] = []
        reliability_pass = 0
        reliability_total = 0
        for row in config_rows:
            total = (row.get("latency_ms") or {}).get("total")
            if total is not None:
                try:
                    totals.append(float(total))
                except (TypeError, ValueError):
                    pass
            verdict = evaluate_reliability_authoritative(row)
            reliability_total += 1
            if verdict["reliability_pass"]:
                reliability_pass += 1

        stats[label] = {
            "config_label": label,
            "row_count": len(config_rows),
            "avg_total_latency_ms": statistics.mean(totals) if totals else None,
            "reliability_rate": (
                reliability_pass / reliability_total if reliability_total else 0.0
            ),
            "reliability_pass": reliability_pass,
            "reliability_total": reliability_total,
        }
    return stats


def recommend_default_config(
    rows: list[dict[str, Any]],
    *,
    path: str = "text",
) -> dict[str, Any]:
    """Pick the recommended default config from benchmark rows.

    Returns a dict with keys:
        recommended_config, reason, candidates, path
    """
    stats = _config_stats(rows, path=path)
    if not stats:
        return {
            "recommended_config": None,
            "reason": f"no rows for path={path!r}",
            "candidates": [],
            "path": path,
        }

    candidates = sorted(
        stats.values(),
        key=lambda s: (
            s["avg_total_latency_ms"] if s["avg_total_latency_ms"] is not None else float("inf"),
            -s["reliability_rate"],
        ),
    )

    with_latency = [c for c in candidates if c["avg_total_latency_ms"] is not None]
    if not with_latency:
        best = max(candidates, key=lambda c: c["reliability_rate"])
        return {
            "recommended_config": best["config_label"],
            "reason": "no latency data; chose highest reliability",
            "candidates": candidates,
            "path": path,
        }

    best = with_latency[0]
    best_lat = best["avg_total_latency_ms"]
    tied = [
        c
        for c in with_latency
        if best_lat and abs(c["avg_total_latency_ms"] - best_lat) / best_lat <= LATENCY_TIE_THRESHOLD
    ]

    if len(tied) > 1:
        winner = max(tied, key=lambda c: c["reliability_rate"])
        reason = (
            f"latency within {int(LATENCY_TIE_THRESHOLD * 100)}% tie band; "
            f"chose highest reliability ({winner['reliability_rate']:.1%})"
        )
    else:
        winner = best
        reason = f"lowest avg total latency ({winner['avg_total_latency_ms']:.1f} ms)"

    return {
        "recommended_config": winner["config_label"],
        "reason": reason,
        "candidates": candidates,
        "path": path,
    }


def format_recommendation_section(rows: list[dict[str, Any]], *, path: str = "text") -> str:
    """Return a text block suitable for aggregate report or wiki paste."""
    result = recommend_default_config(rows, path=path)
    lines = [
        "Default Configuration Recommendation",
        "=" * 60,
        f"Path: {path}",
        "",
    ]

    if not result["candidates"]:
        lines.append(f"No data: {result['reason']}")
        return "\n".join(lines)

    lines.append(
        f"{'Config':<40} {'Avg total (ms)':>14} {'Reliability':>12}"
    )
    lines.append("-" * 68)
    for cand in result["candidates"]:
        lat = cand["avg_total_latency_ms"]
        lat_str = f"{lat:.1f}" if lat is not None else "—"
        rel = f"{cand['reliability_rate']:.1%}"
        marker = "  ← recommended" if cand["config_label"] == result["recommended_config"] else ""
        lines.append(
            f"{cand['config_label']:<40} {lat_str:>14} {rel:>12}{marker}"
        )

    lines.extend(
        [
            "",
            f"Recommended: {result['recommended_config']}",
            f"Reason: {result['reason']}",
            "",
            "Methodology: primary = lowest avg latency_ms.total; "
            f"secondary = reliability when within {int(LATENCY_TIE_THRESHOLD * 100)}%.",
        ]
    )
    return "\n".join(lines)
