"""Authoritative tool-reliability evaluation layer — issue #68.

Operates on already-parsed JSONL rows (written by ComponentResultWriter).
Builds on the harness-computed tool_reliability fields rather than re-calling
the backend; provides a clean pass/fail verdict with a human-readable reason
and extends result_incorporated handling beyond data_extraction.
"""

from __future__ import annotations

# Tools that fire and immediately hand off control — there is no reply body
# into which a result could be incorporated, so result_incorporated is N/A.
_IMMEDIATE_TOOLS: frozenset[str] = frozenset({"agent_transfer", "end_call"})


def evaluate_reliability_authoritative(row: dict) -> dict:
    """Return an authoritative reliability verdict for one parsed JSONL row.

    Parameters
    ----------
    row:
        A dict produced by BenchmarkResultRow.to_dict() and parsed back from JSONL.

    Returns
    -------
    dict with keys:
        reliability_pass (bool)      — overall pass/fail for this row
        tool_correct     (bool)      — tool selection was correct
        result_incorporated (bool|None) — True/False for data_extraction;
                                          None when N/A (immediate tools, no-tool cases)
        reason           (str)       — human-readable explanation of the verdict
    """
    prompt = row.get("prompt") or {}
    expects_tool: bool = bool(prompt.get("expects_tool"))
    expected_type: str | None = prompt.get("expected_tool_type")

    tr = row.get("tool_reliability") or {}
    tool_was_invoked: bool = bool(tr.get("tool_was_invoked"))
    invoked_type: str | None = tr.get("invoked_tool_type")

    if not expects_tool:
        tool_correct = not tool_was_invoked
        reliability_pass = tool_correct
        result_incorporated: bool | None = None
        reason = (
            f"tool fired unexpectedly: {invoked_type}"
            if tool_was_invoked
            else "no tool fired as expected"
        )
        return {
            "reliability_pass": reliability_pass,
            "tool_correct": tool_correct,
            "result_incorporated": result_incorporated,
            "reason": reason,
        }

    # With-tool cases: must invoke the correct tool type.
    if not tool_was_invoked:
        tool_correct = False
        reason = f"expected {expected_type}, no tool invoked"
    elif invoked_type != expected_type:
        tool_correct = False
        reason = f"expected {expected_type}, got {invoked_type}"
    else:
        tool_correct = True
        reason = f"correct tool invoked: {invoked_type}"

    reliability_pass = tool_correct

    # result_incorporated: reuse the harness value for data_extraction;
    # mark immediate tools as N/A (None) — no reply content to check.
    if invoked_type in _IMMEDIATE_TOOLS:
        result_incorporated = None
    elif invoked_type == "data_extraction":
        result_incorporated = tr.get("result_incorporated_in_reply")
    else:
        result_incorporated = None

    return {
        "reliability_pass": reliability_pass,
        "tool_correct": tool_correct,
        "result_incorporated": result_incorporated,
        "reason": reason,
    }


def summarize_reliability(rows: list[dict]) -> dict:
    """Aggregate authoritative verdicts per (config_label, prompt.category).

    Parameters
    ----------
    rows:
        List of dicts produced by BenchmarkResultRow.to_dict().

    Returns
    -------
    Dict keyed by "{config_label}__{category}" where each value is:
        config_label     (str)
        category         (str)
        pass             (int)
        fail             (int)
        total            (int)
        reliability_rate (float)  — pass / total, 0.0 when total == 0
    """
    buckets: dict[str, dict] = {}

    for row in rows:
        config_label = row.get("config_label") or "unknown"
        category = (row.get("prompt") or {}).get("category") or "unknown"
        key = f"{config_label}__{category}"

        if key not in buckets:
            buckets[key] = {
                "config_label": config_label,
                "category": category,
                "pass": 0,
                "fail": 0,
                "total": 0,
                "reliability_rate": 0.0,
            }

        verdict = evaluate_reliability_authoritative(row)
        buckets[key]["total"] += 1
        if verdict["reliability_pass"]:
            buckets[key]["pass"] += 1
        else:
            buckets[key]["fail"] += 1

    for bucket in buckets.values():
        total = bucket["total"]
        bucket["reliability_rate"] = bucket["pass"] / total if total else 0.0

    return buckets
