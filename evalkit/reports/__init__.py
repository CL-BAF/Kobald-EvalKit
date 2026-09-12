"""Reports: terminal summary + Markdown report per run.

The Markdown report states the aggregate formula and its limitations
next to every weighted_pass_rate figure (contract: documented aggregate,
no overall "score" number, no sub-millisecond latency claims).
"""

from __future__ import annotations

from ..models import RunRecord
from ..scoring import AGGREGATE_FORMULA, AGGREGATE_LIMITATIONS

__all__ = ["terminal_summary", "markdown_report", "suite_breakdown"]


def _fmt_rate(rate: float | None) -> str:
    if rate is None:
        return "n/a (no scoreable cases — all need human review)"
    return f"{rate * 100:.1f}%"


_SUMMARY_STATUS_KEYS = (
    ("passed", "PASS"),
    ("failed", "FAIL"),
    ("needs_human", "NEEDS HUMAN"),
    ("errors", "ERROR"),
)


def terminal_summary(record: RunRecord) -> str:
    """Compact run summary for the CLI (stdout)."""
    summary = record.summary
    lines = [
        f"Run {record.run_id}",
        f"provider={record.provider} model={record.model}",
        (
            f"cases: {summary['total_cases']}  "
            + "  ".join(
                f"{label}: {summary.get(key, 0)}"
                for key, label in _SUMMARY_STATUS_KEYS
            )
        ),
        f"weighted pass rate: {_fmt_rate(summary.get('weighted_pass_rate'))}",
        f"duration: {record.duration_ms / 1000.0:.1f}s",
    ]
    for result in record.results:
        marker = {
            "passed": "PASS",
            "failed": "FAIL",
            "needs_human": "HUMAN",
            "error": "ERR!",
        }[result.status]
        line = f"  [{marker}] {result.case_id}"
        if result.status == "error" and result.error:
            line += f" — {result.error}"
        lines.append(line)
    return "\n".join(lines)


def suite_breakdown(record: RunRecord) -> dict[str, dict]:
    """Per-suite pass/total counts (needs_human listed separately)."""
    breakdown: dict[str, dict] = {}
    for result in record.results:
        entry = breakdown.setdefault(
            result.suite, {"total": 0, "passed": 0, "failed": 0, "needs_human": 0, "error": 0}
        )
        entry["total"] += 1
        entry[result.status] += 1
    return breakdown


def markdown_report(record: RunRecord) -> str:
    """Full Markdown report for runs/<run_id>/report.md."""
    summary = record.summary
    out: list[str] = []
    out.append(f"# EvalKit run {record.run_id}")
    out.append("")
    out.append(f"- Generated: {record.timestamp_utc}")
    out.append(f"- EvalKit version: {record.evalkit_version}")
    out.append(f"- Provider: `{record.provider}`  Model: `{record.model}`")
    config = record.config
    out.append(f"- Base URL: `{config.get('base_url', '')}`")
    out.append(f"- Suites: {', '.join(config.get('suites', []))}")
    options = config.get("options") or {}
    if options:
        out.append(f"- Options: `{options}`")
    if config.get("allow_non_loopback"):
        out.append(
            "- WARNING: `allow_non_loopback` override active — traffic leaves the "
            "local machine in cleartext HTTP."
        )
    out.append("")

    out.append("## Summary")
    out.append("")
    out.append(
        f"- Cases: {summary['total_cases']} "
        f"(passed {summary['passed']}, failed {summary['failed']}, "
        f"needs_human {summary['needs_human']}, errors {summary['errors']})"
    )
    out.append(f"- Weighted pass rate: **{_fmt_rate(summary.get('weighted_pass_rate'))}**")
    out.append(f"- Duration: {record.duration_ms / 1000.0:.1f}s")
    breakdown = suite_breakdown(record)
    for suite, counts in breakdown.items():
        out.append(
            f"- Suite `{suite}`: {counts['passed']}/{counts['total']} passed"
            + (f", {counts['needs_human']} need human review" if counts["needs_human"] else "")
            + (f", {counts['error']} errors" if counts["error"] else "")
        )
    out.append("")
    out.append("> Aggregate formula: " + AGGREGATE_FORMULA)
    out.append(">")
    for limitation in AGGREGATE_LIMITATIONS:
        out.append(f"> - {limitation}")
    out.append("")

    needs_human = [r for r in record.results if r.status == "needs_human"]
    if needs_human:
        out.append("## Cases needing human review")
        out.append("")
        for result in needs_human:
            out.append(f"### {result.case_id}")
            for check in result.score.checks:
                if check.needs_human:
                    out.append(f"- **{check.name}** (needs human): {check.detail}")
            out.append("")

    out.append("## Case results")
    out.append("")
    out.append("| Case | Suite | Status | Checks |")
    out.append("|---|---|---|---|")
    for result in record.results:
        checks = ", ".join(
            f"{check.name}: {'pass' if check.passed else 'FAIL'}"
            + (" (needs human)" if check.needs_human else "")
            for check in result.score.checks
        ) or (result.error or "no checks")
        out.append(
            f"| `{result.case_id}` | {result.suite} | {result.status} | {checks} |"
        )
    out.append("")

    out.append("## Failed check details")
    out.append("")
    for result in record.results:
        failures = [c for c in result.score.checks if not c.passed and not c.needs_human]
        if not failures:
            continue
        out.append(f"### {result.case_id}")
        for check in failures:
            out.append(f"- **{check.name}**: {check.detail}")
        out.append("")

    out.append("## Notes on scoring honesty")
    out.append("")
    out.append(
        "Scores are deterministic marker/regex rules, not semantic judgement. "
        "Cases flagged needs_human were NOT verified by automation and are excluded "
        "from the weighted pass rate; they never silently pass or fail."
    )
    out.append("")
    return "\n".join(out) + "\n"