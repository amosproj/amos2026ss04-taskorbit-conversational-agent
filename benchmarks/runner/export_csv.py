"""Human-readable CSV export for component benchmark results (#68).

Produces one Excel-friendly benchmark-summary.csv alongside machine-oriented index.csv.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Any

from recommendation import recommend_default_config
from reliability import evaluate_reliability_authoritative, summarize_reliability

_EXPORT_COLUMNS = [
    "Section",
    "Configuration",
    "Path",
    "Category",
    "Pipeline",
    "STT (ms)",
    "LLM (ms)",
    "Tool (ms)",
    "TTS (ms)",
    "Total avg (ms)",
    "Total min (ms)",
    "Total max (ms)",
    "Success rate",
    "Tool reliability",
    "Trials",
    "Successful",
    "Recommended",
]

_CONFIG_DISPLAY_NAMES: dict[str, str] = {
    "cloud-openai-deepgram-elevenlabs": "Cloud (OpenAI + ElevenLabs)",
    "oss-ollama-deepgram-deepgram": "OSS (Ollama + Deepgram)",
}

_LATENCY_STAGES = (
    "stt_processing",
    "llm_call",
    "tool_call",
    "tts_synthesis",
)

_PROVIDER_LABELS = {
    "deepgram": "Deepgram",
    "openai": "OpenAI",
    "ollama": "Ollama",
    "elevenlabs": "ElevenLabs",
}


def _display_config_name(config_label: str) -> str:
    return _CONFIG_DISPLAY_NAMES.get(config_label, config_label)


def _format_pipeline(cfg: dict[str, Any]) -> str:
    if not cfg:
        return ""
    stt = _PROVIDER_LABELS.get(str(cfg.get("stt_provider", "")), cfg.get("stt_provider", "?"))
    llm = _PROVIDER_LABELS.get(str(cfg.get("llm_provider", "")), cfg.get("llm_provider", "?"))
    tts = _PROVIDER_LABELS.get(str(cfg.get("tts_provider", "")), cfg.get("tts_provider", "?"))
    return (
        f"{stt} {cfg.get('stt_model', '?')}"
        f" → {llm} {cfg.get('llm_model', '?')}"
        f" → {tts} {cfg.get('tts_model', '?')}"
    )


def _format_ms(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.1f}"


def _format_pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"



def _stage_averages(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for stage in _LATENCY_STAGES:
        values: list[float] = []
        for row in rows:
            raw = (row.get("latency_ms") or {}).get(stage)
            if raw is not None:
                try:
                    values.append(float(raw))
                except (TypeError, ValueError):
                    pass
        result[stage] = statistics.mean(values) if values else None
    return result


def _latency_totals(rows: list[dict[str, Any]]) -> list[float]:
    totals: list[float] = []
    for row in rows:
        raw = (row.get("latency_ms") or {}).get("total")
        if raw is not None:
            try:
                totals.append(float(raw))
            except (TypeError, ValueError):
                pass
    return totals


def _row_succeeded(row: dict[str, Any], row_succeeded_fn: Any) -> bool:
    return bool(row_succeeded_fn(row))


def build_export_rows(
    rows: list[dict[str, Any]],
    *,
    row_succeeded_fn: Any,
) -> list[dict[str, str]]:
    """Overall summary rows first, then per-category detail rows."""
    by_config_path: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_category: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        config_label = row.get("config_label") or "unknown"
        path = row.get("path", "text")
        category = (row.get("prompt") or {}).get("category") or "unknown"
        by_config_path.setdefault((config_label, path), []).append(row)
        by_category.setdefault((config_label, path, category), []).append(row)

    export_rows: list[dict[str, str]] = []
    paths_present = sorted({path for _, path in by_config_path})

    for path in paths_present:
        rec = recommend_default_config(rows, path=path)
        recommended = rec.get("recommended_config")

        for config_label in sorted(label for label, p in by_config_path if p == path):
            group = by_config_path[(config_label, path)]
            cfg = (group[0].get("config") or {}) if group else {}
            stages = _stage_averages(group)
            totals = _latency_totals(group)

            success_count = sum(1 for r in group if _row_succeeded(r, row_succeeded_fn))
            total_trials = len(group)
            success_rate = success_count / total_trials if total_trials else 0.0
            rel_pass = sum(
                1 for r in group if evaluate_reliability_authoritative(r)["reliability_pass"]
            )
            rel_rate = rel_pass / total_trials if total_trials else 0.0

            export_rows.append(
                {
                    "Section": "Overall",
                    "Configuration": _display_config_name(config_label),
                    "Path": path,
                    "Category": "",
                    "Pipeline": _format_pipeline(cfg),
                    "STT (ms)": _format_ms(stages.get("stt_processing")),
                    "LLM (ms)": _format_ms(stages.get("llm_call")),
                    "Tool (ms)": _format_ms(stages.get("tool_call")),
                    "TTS (ms)": _format_ms(stages.get("tts_synthesis")),
                    "Total avg (ms)": _format_ms(statistics.mean(totals) if totals else None),
                    "Total min (ms)": _format_ms(min(totals) if totals else None),
                    "Total max (ms)": _format_ms(max(totals) if totals else None),
                    "Success rate": _format_pct(success_rate),
                    "Tool reliability": _format_pct(rel_rate),
                    "Trials": str(total_trials),
                    "Successful": "",
                    "Recommended": "Yes" if config_label == recommended else "No",
                }
            )

        for config_label in sorted({label for label, p, _ in by_category if p == path}):
            for category in sorted(
                cat for label, p, cat in by_category if label == config_label and p == path
            ):
                group = by_category[(config_label, path, category)]
                cat_totals = _latency_totals(group)
                cat_success = sum(1 for r in group if _row_succeeded(r, row_succeeded_fn))
                cat_trials = len(group)
                cat_success_rate = cat_success / cat_trials if cat_trials else 0.0
                rel = summarize_reliability(group)
                rel_rate = (rel.get(category) or {}).get("reliability_rate", 0.0)

                export_rows.append(
                    {
                        "Section": "By category",
                        "Configuration": _display_config_name(config_label),
                        "Path": path,
                        "Category": category,
                        "Pipeline": "",
                        "STT (ms)": "",
                        "LLM (ms)": "",
                        "Tool (ms)": "",
                        "TTS (ms)": "",
                        "Total avg (ms)": _format_ms(
                            statistics.mean(cat_totals) if cat_totals else None
                        ),
                        "Total min (ms)": "",
                        "Total max (ms)": "",
                        "Success rate": _format_pct(cat_success_rate),
                        "Tool reliability": _format_pct(rel_rate),
                        "Trials": str(cat_trials),
                        "Successful": f"{cat_success}/{cat_trials}",
                        "Recommended": "",
                    }
                )

    return export_rows


def write_readable_export(
    results_dir: Path | str,
    rows: list[dict[str, Any]],
    *,
    row_succeeded_fn: Any,
) -> Path:
    """Write a single benchmark-summary.csv (overall + by-category sections)."""
    results_path = Path(results_dir)
    results_path.mkdir(parents=True, exist_ok=True)
    export_file = results_path / "benchmark-summary.csv"

    with open(export_file, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(build_export_rows(rows, row_succeeded_fn=row_succeeded_fn))

    return export_file
