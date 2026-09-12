"""EvalKit command-line interface.

Subcommands: doctor, models, list, run, report, compare.

Exit codes (pinned): 0 success, 1 runtime error, 2 usage error (argparse
default). Runtime errors print a clear stderr message and never a
traceback.

The models/doctor commands flag ':cloud' model tags with a local-operation
warning: EvalKit constrains the ENDPOINT (loopback), not the model tag —
a ':cloud' model routes inference off-machine (v0.1.4).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .cases import SUITES_REGISTRY, discover_suites, load_cases, load_suite
from .compare import compare_runs
from .config import (
    EvalKitConfig,
    build_provider,
    is_cloud_model,
    load_config,
)
from .errors import EvalkitError
from .provider import ProviderConnectionError, ProviderError, ProviderTimeout
from .reports import markdown_report, terminal_summary
from .reports.compare import compare_markdown, compare_terminal
from .store import list_runs, load_run, save_run

__all__ = ["main"]

_CLOUD_WARNING = "cloud relay — inference will leave the local machine"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evalkit",
        description="Local AI evaluation toolkit (stdlib-only, Ollama-first).",
    )
    parser.add_argument("--version", action="version", version=f"evalkit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_config_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", type=Path, default=None, help="config file (default evalkit.json)")
        p.add_argument("--provider", choices=("mock", "ollama"), default=None)
        p.add_argument("--model", default=None, help="model tag, e.g. llama3.1:8b")
        p.add_argument("--base-url", default=None, help="Ollama base URL (loopback by default)")
        p.add_argument(
            "--allow-non-loopback",
            action="store_true",
            default=None,
            help="explicitly allow a non-loopback Ollama endpoint (named intent required)",
        )
        p.add_argument("--timeout", type=float, default=None, help="provider timeout in seconds")

    add_config_args(sub.add_parser("doctor", help="check provider reachability and config health"))
    add_config_args(sub.add_parser("models", help="list models visible through the provider"))

    p_list = sub.add_parser("list", help="list suites and case files")
    add_config_args(p_list)
    p_list.add_argument("--suite", default=None, help="show cases of one suite")

    p_run = sub.add_parser("run", help="run a suite and store result.json + report.md")
    add_config_args(p_run)
    p_run.add_argument("suite", help="suite name under suites/ (or 'all')")
    p_run.add_argument(
        "--runs-dir",
        type=Path,
        default=None,
        help="output directory for runs (default runs/)",
    )
    p_run.add_argument(
        "--no-save",
        action="store_true",
        help="print the summary without persisting a run",
    )

    p_report = sub.add_parser("report", help="print the Markdown report of a stored run")
    add_config_args(p_report)
    p_report.add_argument("run_id", help="run id or path under runs/")

    p_compare = sub.add_parser("compare", help="compare two stored runs")
    add_config_args(p_compare)
    p_compare.add_argument("run_a")
    p_compare.add_argument("run_b")

    return parser


def _resolve_config(args: argparse.Namespace) -> EvalKitConfig:
    overrides = {
        "provider": args.provider,
        "model": args.model,
        "base_url": args.base_url,
        "timeout_s": args.timeout,
        "allow_non_loopback": True if args.allow_non_loopback else None,
    }
    return load_config(config_path=args.config, cli_overrides=overrides)


def _provider_warnings_text(models: list) -> list[str]:
    warnings: list[str] = []
    for info in models:
        if is_cloud_model(info.name):
            warnings.append(f"{info.name}: {_CLOUD_WARNING}")
    return warnings


def _cmd_doctor(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    print(f"evalkit {__version__}")
    print(f"provider: {config.provider}")
    print(f"model: {config.model or '(none set)'}")
    print(f"base_url: {config.base_url}")
    if config.provider == "ollama" and config.allow_non_loopback:
        print(
            "WARNING: allow_non_loopback override is ACTIVE — traffic to "
            f"{config.base_url} leaves the local machine in cleartext HTTP."
        )
    suites_dir = config.suites_dir
    if suites_dir.is_dir():
        print(f"suites dir: {suites_dir} ({', '.join(discover_suites(suites_dir)) or 'empty'})")
    else:
        print(f"suites dir: {suites_dir} (missing)")
    provider = build_provider(config)
    try:
        models = provider.list_models()
    except ProviderError as exc:
        print(f"provider: UNREACHABLE — {exc}")
        return 1
    print(f"provider: reachable ({len(models)} models visible)")
    for warning in _provider_warnings_text(models):
        print(f"WARNING: {warning}")
    return 0


def _cmd_models(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    provider = build_provider(config)
    try:
        models = provider.list_models()
    except ProviderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    payload = {
        "provider": provider.name,
        "models": [
            {"name": info.name, "size_bytes": info.size_bytes, "cloud": is_cloud_model(info.name)}
            for info in models
        ],
        "warnings": _provider_warnings_text(models),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    suites_dir = config.suites_dir
    if not suites_dir.is_dir():
        print(f"error: suites directory not found: {suites_dir}", file=sys.stderr)
        return 1
    if args.suite:
        if args.suite not in SUITES_REGISTRY:
            print(
                f"error: unknown suite {args.suite!r} "
                f"(registered: {', '.join(SUITES_REGISTRY)})",
                file=sys.stderr,
            )
            return 1
        suite_names = [args.suite]
    else:
        suite_names = discover_suites(suites_dir)
        if not suite_names:
            print(f"no suites with case files under {suites_dir}")
            return 0
    for suite in suite_names:
        cases = load_suite(suites_dir, suite)
        print(f"{suite} ({len(cases)} cases)")
        for case in cases:
            print(f"  {case.case_id}: {case.title}")
    return 0


def _resolve_suites(config: EvalKitConfig, suite_arg: str) -> dict[str, list]:
    suites_dir = config.suites_dir
    if not suites_dir.is_dir():
        raise EvalkitError(f"suites directory not found: {suites_dir}")
    if suite_arg == "all":
        names = discover_suites(suites_dir)
        if not names:
            raise EvalkitError(f"no suites with case files under {suites_dir}")
    elif suite_arg in SUITES_REGISTRY:
        names = [suite_arg]
    else:
        raise EvalkitError(
            f"unknown suite {suite_arg!r} (registered: {', '.join(SUITES_REGISTRY)})"
        )
    return load_cases(suites_dir, names)


def _cmd_run(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    if config.provider != "mock" and not config.model:
        print(
            "error: no model configured; pass --model <tag> (see: evalkit models)",
            file=sys.stderr,
        )
        return 1
    suites = _resolve_suites(config, args.suite)

    from .runner import run_cases

    provider = build_provider(config)
    record = run_cases(provider=provider, config=config, suites=suites)

    if args.no_save:
        print(terminal_summary(record))
        return 0

    runs_dir = args.runs_dir or config.runs_dir
    report_md = markdown_report(record)
    saved = save_run(record, runs_dir, report_markdown=report_md)
    print(terminal_summary(saved))
    print(f"\nstored: {runs_dir / saved.run_id}")
    return 0


def _resolve_run_path(runs_dir: Path, run_ref: str) -> Path:
    candidate = Path(run_ref)
    if candidate.exists():
        return candidate
    return runs_dir / run_ref


def _cmd_report(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    path = _resolve_run_path(config.runs_dir, args.run_id)
    record = load_run(path)
    print(markdown_report(record), end="")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    record_a = load_run(_resolve_run_path(config.runs_dir, args.run_a))
    record_b = load_run(_resolve_run_path(config.runs_dir, args.run_b))
    comparison = compare_runs(record_a, record_b)
    print(compare_terminal(comparison))
    print()
    print(compare_markdown(comparison), end="")
    return 0


_COMMANDS = {
    "doctor": _cmd_doctor,
    "models": _cmd_models,
    "list": _cmd_list,
    "run": _cmd_run,
    "report": _cmd_report,
    "compare": _cmd_compare,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS[args.command]
    try:
        return handler(args)
    except EvalkitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ProviderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())