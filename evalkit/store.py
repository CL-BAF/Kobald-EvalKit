"""Run persistence: runs/<run_id>/result.json + report.md.

Pinned behaviors (v0.1.2 #3, v0.1.3 R9, v0.1.8):

- run_id = UTC timestamp "YYYYmmddTHHMMSSZ" + "-" + 8 hex chars,
  filesystem-safe; allocation retries on directory collision (max 5).
- Writes are ATOMIC: a temp file is written in the target directory and
  os.replace()d into place, so an interrupted run leaves a complete or
  absent result.json — never truncated.
- CREDENTIAL REDACTION lives in the persistence flow itself, BEFORE the
  atomic write (not a post-write cleanup pass): top-level keys of
  GenerationResult.raw that look credential-like (authorization,
  api_key, x-api-key, token-style variants; case-insensitive, the
  over-matching direction is acceptable) are replaced with the visible
  marker "[redacted]" — keys are never silently dropped, so a reader of
  result.json can distinguish "backend sent nothing" from "we stripped
  it". Redaction is recursive at depth 1+: nested dicts/lists inside raw
  are walked so a backend cannot bury a key one level down.

Round-trip guarantee: RunRecord.from_dict(json.loads(result.json)) equals
the persisted record (see models.py).
"""

from __future__ import annotations

import json
import os
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path

from .errors import StoreError
from .models import RunRecord

__all__ = [
    "REDACTED_MARKER",
    "REDACT_KEYS",
    "redact_raw",
    "new_run_id",
    "allocate_run_dir",
    "save_run",
    "load_run",
    "list_runs",
]

REDACTED_MARKER = "[redacted]"
REDACT_SUBSTRINGS = ("authorization", "api_key", "apikey", "x-api-key", "token", "secret", "password", "credential")
MAX_RUN_ID_ATTEMPTS = 5
_HEX = string.hexdigits[:16]


def _is_credential_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in REDACT_SUBSTRINGS)


def redact_raw(raw: dict) -> dict:
    """Return a copy of raw with credential-like values visibly redacted.

    Top-level plus nested dict keys are matched case-insensitively against
    the REDACT_SUBSTRINGS list (over-matching is acceptable, under-matching
    is not). Values are replaced with "[redacted]"; keys are never dropped.
    """
    if not isinstance(raw, dict):
        return {}
    return _redact_value(raw)


def _redact_value(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict = {}
        for key, item in value.items():
            if isinstance(key, str) and _is_credential_key(key):
                redacted[key] = REDACTED_MARKER
            else:
                redacted[key] = _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def new_run_id(now: datetime | None = None) -> str:
    """YYYYmmddTHHMMSSZ-XXXXXXXX (UTC stamp + 8 hex chars)."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(4)}"


def allocate_run_dir(runs_dir: Path, *, _attempts: int = MAX_RUN_ID_ATTEMPTS) -> tuple[str, Path]:
    """Create runs/<run_id>/ with retry-on-collision (max 5 attempts)."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    last_error: OSError | None = None
    for _ in range(_attempts):
        run_id = new_run_id()
        run_dir = runs_dir / run_id
        try:
            run_dir.mkdir()
            return run_id, run_dir
        except FileExistsError as exc:
            last_error = exc
    raise StoreError(
        f"could not allocate a unique run directory in {runs_dir} "
        f"after {_attempts} attempts (last collision: {last_error})"
    )


def save_run(record: RunRecord, runs_dir: Path, *, report_markdown: str | None = None) -> RunRecord:
    """Persist a run atomically; returns the persisted RunRecord (with
    run_id assigned by allocate_run_dir when the caller left it blank —
    the runner leaves it blank; the store owns allocation with
    retry-on-collision).

    Credential redaction (redact_raw) is applied inside this persistence
    path, before the atomic write. Both result.json and (when given)
    report.md are written via tmp-file + os.replace.
    """
    if record.run_id:
        run_id = record.run_id
        run_dir = runs_dir / run_id
    else:
        run_id, run_dir = allocate_run_dir(runs_dir)
    record = RunRecord(
        run_id=run_id,
        timestamp_utc=record.timestamp_utc,
        evalkit_version=record.evalkit_version,
        provider=record.provider,
        model=record.model,
        config=record.config,
        results=record.results,
        summary=record.summary,
        duration_ms=record.duration_ms,
    )
    payload = record.to_dict()
    results = payload.get("results")
    if isinstance(results, list):
        for entry in results:
            generation = entry.get("generation") if isinstance(entry, dict) else None
            if isinstance(generation, dict) and isinstance(generation.get("raw"), dict):
                generation["raw"] = redact_raw(generation["raw"])
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(run_dir / "result.json", payload)
        if report_markdown is not None:
            _atomic_write_text(run_dir / "report.md", report_markdown)
    except OSError as exc:
        raise StoreError(f"failed to persist run {run_id}: {exc}") from exc
    return RunRecord.from_dict(payload)


def _atomic_write_json(target: Path, payload: dict) -> None:
    _atomic_write_text(target, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _atomic_write_text(target: Path, text: str) -> None:
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)


def load_run(path: Path) -> RunRecord:
    """Load result.json (file or run directory) into a RunRecord."""
    result_path = path if path.is_file() else path / "result.json"
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise StoreError(f"cannot read {result_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise StoreError(f"{result_path}: corrupt result.json ({exc})") from exc
    try:
        return RunRecord.from_dict(data)
    except (ValueError, TypeError, KeyError) as exc:
        raise StoreError(f"{result_path}: does not match the run record schema ({exc})") from exc


def list_runs(runs_dir: Path) -> list[Path]:
    """Run directories sorted oldest-first, those containing result.json."""
    if not runs_dir.is_dir():
        return []
    return sorted(
        entry
        for entry in runs_dir.iterdir()
        if entry.is_dir() and (entry / "result.json").is_file()
    )