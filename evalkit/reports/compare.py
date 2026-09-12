"""Markdown + terminal rendering for compare output."""

from __future__ import annotations

from ..compare import Comparison

__all__ = ["compare_markdown", "compare_terminal"]


def _rate(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 100:.1f}%"
    return str(value)


def compare_terminal(comparison: Comparison) -> str:
    lines = [
        f"Comparing {comparison.run_id_a} (a) -> {comparison.run_id_b} (b)",
        "",
    ]
    if comparison.summary_delta:
        for key, delta in comparison.summary_delta.items():
            if key == "weighted_pass_rate":
                lines.append(f"  {key}: {_rate(delta['a'])} -> {_rate(delta['b'])}")
            else:
                lines.append(f"  {key}: {delta['a']} -> {delta['b']}")
    else:
        lines.append("  no summary changes")
    changed = [c for c in comparison.cases if c.changed]
    if changed:
        lines.append("")
        lines.append(f"  changed cases ({len(changed)}):")
        for case in changed:
            lines.append(f"    {case.case_id}: {case.status_a} -> {case.status_b}")
    return "\n".join(lines)


def compare_markdown(comparison: Comparison) -> str:
    out = [
        f"# Compare: {comparison.run_id_a} vs {comparison.run_id_b}",
        "",
        "| Case | Suite | A | B |",
        "|---|---|---|---|",
    ]
    for case in comparison.cases:
        marker = " *" if case.changed else ""
        out.append(f"| `{case.case_id}`{marker} | {case.suite} | {case.status_a} | {case.status_b} |")
    out.append("")
    out.append("(* = status changed)")
    out.append("")
    if comparison.summary_delta:
        out.append("## Summary deltas")
        out.append("")
        for key, delta in comparison.summary_delta.items():
            if key == "weighted_pass_rate":
                out.append(f"- {key}: {_rate(delta['a'])} -> {_rate(delta['b'])}")
            else:
                out.append(f"- {key}: {delta['a']} -> {delta['b']}")
        out.append("")
    return "\n".join(out) + "\n"