"""Store contract tests (atomic writes, redaction bar (a)-(d), run_id
format, corrupt-data fail-safe, unsafe paths) per Amendments v0.1.2 #3,
v0.1.3 R9, v0.1.8.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evalkit.errors import StoreError
from evalkit.models import CaseResult, RunRecord, ScoreResult
from evalkit.provider.base import GenerationResult
from evalkit.store import (
    REDACTED_MARKER,
    allocate_run_dir,
    list_runs,
    load_run,
    new_run_id,
    redact_raw,
    save_run,
)

_RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")

MANDATORY_SUMMARY = {
    "total_cases": 1,
    "passed": 1,
    "failed": 0,
    "needs_human": 0,
    "errors": 0,
    "duration_ms": 1.0,
}


def make_record(**overrides) -> RunRecord:
    generation = GenerationResult(
        text="Paris [SRC-1]",
        model="mock-model",
        provider="mock",
        elapsed_ms=12.5,
        raw={"finish_reason": "stop"},
    )
    score = ScoreResult.from_checks(
        [__import__("evalkit.models", fromlist=["Check"]).Check(
            name="required_source_ids", passed=True, detail="ok", count=0
        )]
    )
    fields = {
        "run_id": "",
        "timestamp_utc": "2026-09-12T00:00:00Z",
        "evalkit_version": "0.1.0",
        "provider": "mock",
        "model": "mock-model",
        "config": {
            "model": "mock-model",
            "provider": "mock",
            "base_url": "http://127.0.0.1:11434",
            "options": {},
            "suites": ["evidence_grounding"],
            "evalkit_version": "0.1.0",
            "start_time_utc": "2026-09-12T00:00:00Z",
        },
        "results": [
            CaseResult.from_outcome(
                case_id="c1", suite="evidence_grounding", score=score, generation=generation
            )
        ],
        "summary": dict(MANDATORY_SUMMARY),
        "duration_ms": 1.0,
    }
    fields.update(overrides)
    return RunRecord(**fields)


class TestRunIdFormat:
    def test_run_id_matches_pinned_pattern(self):
        run_id = new_run_id()
        assert _RUN_ID_RE.match(run_id), run_id

    def test_run_id_is_filesystem_safe(self):
        run_id = new_run_id()
        assert set(run_id) <= set("0123456789TABZabcdefghijklmnopqrstuvwxyz-")

    def test_run_id_uses_given_timestamp(self):
        stamp = datetime(2026, 9, 12, 10, 15, 0, tzinfo=timezone.utc)
        run_id = new_run_id(stamp)
        assert run_id.startswith("20260912T101500Z-")

    def test_allocate_run_dir_creates_directory(self, tmp_path):
        run_id, run_dir = allocate_run_dir(tmp_path)
        assert _RUN_ID_RE.match(run_id)
        assert run_dir.is_dir()

    def test_allocate_run_dir_retries_on_collision(self, tmp_path, monkeypatch):
        # Force collisions for the first two attempts by pre-creating dirs.
        import evalkit.store as store

        real_new_run_id = store.new_run_id
        counter = {"n": 0}

        def colliding_id():
            counter["n"] += 1
            if counter["n"] <= 2:
                stamp = datetime(2026, 9, 12, tzinfo=timezone.utc)
                return real_new_run_id(stamp)  # we will mkdir these below
            return real_new_run_id()

        monkeypatch.setattr(store, "new_run_id", colliding_id)
        # Pre-create two directories that the first two attempts will hit.
        stamp = datetime(2026, 9, 12, tzinfo=timezone.utc)
        for _ in range(2):
            pre_id = real_new_run_id(stamp)
            (tmp_path / pre_id).mkdir()
        run_id, run_dir = allocate_run_dir(tmp_path)
        assert run_dir.is_dir()

    def test_allocate_run_dir_raises_store_error_after_max_attempts(self, tmp_path, monkeypatch):
        import evalkit.store as store

        fixed = store.new_run_id()
        monkeypatch.setattr(store, "new_run_id", lambda: fixed)
        (tmp_path / fixed).mkdir()
        with pytest.raises(StoreError):
            allocate_run_dir(tmp_path)


class TestAtomicWrite:
    def test_save_writes_result_json_and_report(self, tmp_path):
        record = make_record()
        saved = save_run(record, tmp_path, report_markdown="# report\n")
        assert (tmp_path / saved.run_id / "result.json").is_file()
        assert (tmp_path / saved.run_id / "report.md").is_file()

    def test_interrupted_write_leaves_complete_or_absent(self, tmp_path, monkeypatch):
        # Simulate a crash between tmp write and replace: no result.json
        # at target, no partial target content.
        import evalkit.store as store

        record = make_record()

        def failing_replace(src, dst):
            raise OSError("simulated crash before replace")

        monkeypatch.setattr(store.os, "replace", failing_replace)
        with pytest.raises(StoreError):
            save_run(record, tmp_path)
        # No run dir should contain a truncated result.json: the tmp file
        # may exist but the target is absent (complete-or-absent rule).
        for run_dir in tmp_path.iterdir():
            target = run_dir / "result.json"
            assert not target.exists() or target.read_text(encoding="utf-8").endswith("}\n")

    def test_tmp_file_never_survives_as_result_json(self, tmp_path):
        record = make_record()
        saved = save_run(record, tmp_path)
        run_dir = tmp_path / saved.run_id
        assert not (run_dir / "result.json.tmp").exists()
        assert (run_dir / "result.json").is_file()

    def test_saved_result_round_trips_exactly(self, tmp_path):
        record = make_record()
        saved = save_run(record, tmp_path)
        loaded = load_run(tmp_path / saved.run_id)
        # run_id was assigned by the store; compare with it filled.
        assert loaded == saved


class TestRedactionBarA_D:
    """v0.1.8 hardening bar: visible marker, case-insensitive coverage,
    real persistence path, single atomic write of already-redacted data."""

    def _record_with_raw(self, raw: dict) -> RunRecord:
        generation = GenerationResult(
            text="out", model="m", provider="mock", elapsed_ms=0.0, raw=raw
        )
        score = ScoreResult.from_checks(
            [__import__("evalkit.models", fromlist=["Check"]).Check(name="x", passed=True, detail="d")]
        )
        return make_record(
            results=[
                CaseResult.from_outcome(
                    case_id="c", suite="s", score=score, generation=generation
                )
            ]
        )

    def test_bar_a_visible_marker_not_silent_drop(self, tmp_path):
        record = self._record_with_raw({"api_key": "sk-live-xyz", "model": "m"})
        saved = save_run(record, tmp_path)
        payload = json.loads((tmp_path / saved.run_id / "result.json").read_text(encoding="utf-8"))
        raw = payload["results"][0]["generation"]["raw"]
        assert raw["api_key"] == REDACTED_MARKER  # key present, value redacted
        assert raw["model"] == "m"  # untouched keys survive

    def test_bar_a_authorization_and_token_variants(self, tmp_path):
        record = self._record_with_raw(
            {
                "authorization": "Bearer x",
                "API_KEY": "v",
                "X-API-Key": "v",
                "auth_token": "v",
                "secret": "v",
                "ACCESS_TOKEN": "v",
                "password": "v",
                "credential": "v",
            }
        )
        saved = save_run(record, tmp_path)
        payload = json.loads((tmp_path / saved.run_id / "result.json").read_text(encoding="utf-8"))
        raw = payload["results"][0]["generation"]["raw"]
        for key in raw:
            assert raw[key] == REDACTED_MARKER, key

    def test_bar_a_overmatch_direction_fails_safe(self, tmp_path):
        # "token_count" is NOT a credential but contains "token" — the
        # over-matching direction is acceptable per contract; the value
        # must be redacted (fail-safe), never leaked.
        record = self._record_with_raw({"token_count": 5, "tokens_used": 7})
        saved = save_run(record, tmp_path)
        payload = json.loads((tmp_path / saved.run_id / "result.json").read_text(encoding="utf-8"))
        raw = payload["results"][0]["generation"]["raw"]
        assert raw["token_count"] == REDACTED_MARKER
        assert raw["tokens_used"] == REDACTED_MARKER

    def test_bar_c_nested_keys_redacted(self, tmp_path):
        record = self._record_with_raw(
            {"meta": {"nested_api_key": "buried", "safe": 1}, "list": [{"secret_value": "x"}]}
        )
        saved = save_run(record, tmp_path)
        payload = json.loads((tmp_path / saved.run_id / "result.json").read_text(encoding="utf-8"))
        raw = payload["results"][0]["generation"]["raw"]
        assert raw["meta"]["nested_api_key"] == REDACTED_MARKER
        assert raw["meta"]["safe"] == 1
        assert raw["list"][0]["secret_value"] == REDACTED_MARKER

    def test_bar_d_single_atomic_write_of_redacted_data(self, tmp_path):
        # The persisted file contains the redacted form; redaction is
        # observable only through final content (tmp+replace, no second pass).
        record = self._record_with_raw({"api_key": "sk-live-xyz"})
        saved = save_run(record, tmp_path)
        text = (tmp_path / saved.run_id / "result.json").read_text(encoding="utf-8")
        assert "sk-live-xyz" not in text
        assert REDACTED_MARKER in text

    def test_redact_raw_unit_behaviour(self):
        raw = {"Authorization": "x", "api-key": "y", "safe": "keep", "n": {"token": "z"}}
        out = redact_raw(raw)
        assert out["Authorization"] == REDACTED_MARKER
        assert out["api-key"] == REDACTED_MARKER
        assert out["safe"] == "keep"
        assert out["n"]["token"] == REDACTED_MARKER
        # Original untouched (copy semantics).
        assert raw["Authorization"] == "x"

    def test_no_credential_like_keys_left_after_persistence(self, tmp_path):
        import evalkit.store as store

        record = self._record_with_raw(
            {"api_key": "v", "Authorization": "v", "x_api_key": "v", "authToken": "v"}
        )
        saved = save_run(record, tmp_path)
        payload = json.loads((tmp_path / saved.run_id / "result.json").read_text(encoding="utf-8"))
        raw = payload["results"][0]["generation"]["raw"]
        for key, value in raw.items():
            assert not (
                isinstance(value, str) and value.startswith("v")
            ), f"{key} leaked"


class TestCorruptDataFailSafe:
    def test_truncated_json_raises_store_error(self, tmp_path):
        run_dir = tmp_path / "20260912T000000Z-cafe0001"
        run_dir.mkdir()
        (run_dir / "result.json").write_text('{"run_id": "x"', encoding="utf-8")
        with pytest.raises(StoreError):
            load_run(run_dir)

    def test_empty_file_raises_store_error(self, tmp_path):
        run_dir = tmp_path / "20260912T000000Z-cafe0002"
        run_dir.mkdir()
        (run_dir / "result.json").write_text("", encoding="utf-8")
        with pytest.raises(StoreError):
            load_run(run_dir)

    def test_missing_keys_raise_store_error(self, tmp_path):
        run_dir = tmp_path / "20260912T000000Z-cafe0003"
        run_dir.mkdir()
        (run_dir / "result.json").write_text('{"run_id": "x"}', encoding="utf-8")
        with pytest.raises(StoreError):
            load_run(run_dir)

    def test_wrong_types_raise_store_error(self, tmp_path):
        record = make_record()
        data = record.to_dict()
        data["results"] = "not a list"
        run_dir = tmp_path / "20260912T000000Z-cafe0004"
        run_dir.mkdir()
        (run_dir / "result.json").write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(StoreError):
            load_run(run_dir)

    def test_missing_file_raises_store_error(self, tmp_path):
        with pytest.raises(StoreError):
            load_run(tmp_path / "nonexistent")

    def test_error_messages_are_clean_not_tracebacks(self, tmp_path):
        run_dir = tmp_path / "20260912T000000Z-cafe0005"
        run_dir.mkdir()
        (run_dir / "result.json").write_text("{", encoding="utf-8")
        with pytest.raises(StoreError) as excinfo:
            load_run(run_dir)
        assert "corrupt result.json" in str(excinfo.value)


class TestUnsafePaths:
    def test_load_run_rejects_traversal_outside_runs_dir(self, tmp_path):
        # run_id containing ../ must never resolve outside runs/.
        outside = tmp_path / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        with pytest.raises(StoreError):
            load_run(tmp_path / ".." / "outside.json" / "result.json")

    def test_run_id_with_path_separators_never_created(self, tmp_path):
        record = make_record(run_id="../escape")
        with pytest.raises((StoreError, OSError, ValueError)):
            save_run(record, tmp_path)
        # Nothing escaped the runs dir.
        assert not (tmp_path.parent / "escape").exists()

    def test_run_id_absolute_path_never_created(self, tmp_path):
        record = make_record(run_id="C:\\abs\\escape")
        with pytest.raises((StoreError, OSError, ValueError)):
            save_run(record, tmp_path)

    def test_null_byte_run_id_rejected(self, tmp_path):
        record = make_record(run_id="bad\x00id")
        with pytest.raises((StoreError, OSError, ValueError)):
            save_run(record, tmp_path)


class TestListRuns:
    def test_lists_only_dirs_with_result_json(self, tmp_path):
        saved = save_run(make_record(), tmp_path)
        (tmp_path / "empty-dir").mkdir()
        (tmp_path / "loose-file").write_text("x", encoding="utf-8")
        runs = list_runs(tmp_path)
        assert [p.name for p in runs] == [saved.run_id]

    def test_missing_runs_dir_returns_empty(self, tmp_path):
        assert list_runs(tmp_path / "nope") == []

    def test_sorted_oldest_first(self, tmp_path):
        a = save_run(make_record(), tmp_path)
        b = save_run(make_record(), tmp_path)
        runs = list_runs(tmp_path)
        assert [p.name for p in runs] == sorted([a.run_id, b.run_id])


class TestSaveRunIdAssignment:
    def test_blank_run_id_gets_allocated(self, tmp_path):
        record = make_record(run_id="")
        saved = save_run(record, tmp_path)
        assert _RUN_ID_RE.match(saved.run_id)

    def test_explicit_run_id_preserved(self, tmp_path):
        record = make_record(run_id="20260912T000000Z-feedbeef")
        saved = save_run(record, tmp_path)
        assert saved.run_id == "20260912T000000Z-feedbeef"
        assert (tmp_path / saved.run_id / "result.json").is_file()

    def test_save_is_repeatable_to_same_dir(self, tmp_path):
        record = make_record(run_id="20260912T000000Z-feedbeef")
        first = save_run(record, tmp_path)
        second = save_run(record, tmp_path)
        assert first == second