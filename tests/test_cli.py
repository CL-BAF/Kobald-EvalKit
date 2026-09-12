"""CLI contract tests: subcommands, pinned exit codes (0/1/2), bad paths,
no-save mode, doctor/models behaviour, :cloud flag, report/compare."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalkit.cli import main


@pytest.fixture()
def suites_root(tmp_path, monkeypatch):
    """Point config at a temp suites dir with the real repo suites copied."""
    repo = Path(__file__).resolve().parent.parent
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    for suite_dir in (repo / "suites").iterdir():
        if suite_dir.is_dir():
            (suites_dir / suite_dir.name).mkdir()
            for case_file in suite_dir.glob("*.json"):
                (suites_dir / suite_dir.name / case_file.name).write_text(
                    case_file.read_text(encoding="utf-8"), encoding="utf-8"
                )
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestUsageAndHelp:
    def test_help_exits_zero(self, capsys):
        # argparse raises SystemExit(0) for --help (stdlib convention).
        with pytest.raises(SystemExit) as excinfo:
            main(["--help"])
        assert excinfo.value.code == 0
        assert "usage:" in capsys.readouterr().out

    def test_bad_subcommand_exits_two(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            main(["vibes"])
        assert excinfo.value.code == 2

    def test_no_command_exits_two(self):
        with pytest.raises(SystemExit) as excinfo:
            main([])
        assert excinfo.value.code == 2

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            main(["--version"])
        assert excinfo.value.code == 0
        assert "evalkit" in capsys.readouterr().out


class TestList:
    def test_list_all_suites(self, suites_root, capsys):
        assert main(["list"]) == 0
        out = capsys.readouterr().out
        assert "evidence_grounding" in out
        assert "cases" in out

    def test_list_single_suite(self, suites_root, capsys):
        assert main(["list", "--suite", "evidence_grounding"]) == 0
        out = capsys.readouterr().out
        assert "eg_cite_all_sources" in out

    def test_list_unknown_suite_exits_one(self, suites_root, capsys):
        assert main(["list", "--suite", "vibes"]) == 1
        err = capsys.readouterr().err
        assert "unknown suite" in err

    def test_list_missing_suites_dir_exits_one(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        assert main(["list"]) == 1
        assert "suites directory not found" in capsys.readouterr().err


class TestRun:
    def test_run_mock_no_save_prints_summary(self, suites_root, capsys):
        assert main(["run", "evidence_grounding", "--provider", "mock", "--no-save"]) == 0
        out = capsys.readouterr().out
        assert "cases:" in out
        assert "weighted pass rate" in out

    def test_run_mock_persists_result_and_report(self, suites_root, capsys):
        assert main(["run", "evidence_grounding", "--provider", "mock"]) == 0
        out = capsys.readouterr().out
        assert "stored:" in out
        runs_dir = suites_root / "runs"
        run_dirs = [d for d in runs_dir.iterdir() if d.is_dir()]
        assert len(run_dirs) == 1
        assert (run_dirs[0] / "result.json").is_file()
        assert (run_dirs[0] / "report.md").is_file()

    def test_run_ollama_without_model_exits_one(self, suites_root, capsys):
        assert main(["run", "evidence_grounding", "--provider", "ollama"]) == 1
        err = capsys.readouterr().err
        assert "no model configured" in err

    def test_run_unknown_suite_exits_one(self, suites_root, capsys):
        assert main(["run", "vibes", "--provider", "mock"]) == 1
        assert "unknown suite" in capsys.readouterr().err

    def test_run_custom_runs_dir(self, tmp_path, suites_root, capsys):
        out_dir = tmp_path / "custom-runs"
        assert main(["run", "evidence_grounding", "--provider", "mock", "--runs-dir", str(out_dir)]) == 0
        assert any((out_dir / d / "result.json").is_file() for d in out_dir.iterdir() if d.is_dir())

    def test_run_mock_with_model(self, suites_root, capsys):
        assert main(["run", "evidence_grounding", "--provider", "mock", "--model", "my-mock"]) == 0
        out = capsys.readouterr().out
        assert "model=my-mock" in out


class TestDoctorModels:
    def test_doctor_mock_reachable(self, suites_root, capsys):
        assert main(["doctor", "--provider", "mock"]) == 0
        out = capsys.readouterr().out
        assert "provider: reachable" in out

    def test_doctor_ollama_unreachable_exits_one(self, suites_root, capsys):
        # Closed loopback port: deterministic refusal, offline.
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        assert main(["doctor", "--provider", "ollama", "--base-url", f"http://127.0.0.1:{port}"]) == 1
        out = capsys.readouterr().out
        assert "UNREACHABLE" in out

    def test_models_mock_outputs_json(self, suites_root, capsys):
        assert main(["models", "--provider", "mock", "--model", "my-mock"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["provider"] == "mock"
        assert payload["models"][0]["name"] == "my-mock"
        assert payload["models"][0]["cloud"] is False

    def test_models_flags_cloud_tags(self, suites_root, capsys, monkeypatch):
        from evalkit.provider.mock import MockProvider
        from evalkit.provider.base import ModelInfo
        from evalkit import cli as cli_mod

        def fake_build(config):
            return MockProvider(model=config.model or "m")

        monkeypatch.setattr(cli_mod, "build_provider", fake_build)
        real_list = MockProvider.list_models

        def cloud_list(self):
            return [ModelInfo(name="llama3:cloud"), ModelInfo(name="llama3")]

        monkeypatch.setattr(MockProvider, "list_models", cloud_list)
        assert main(["models", "--provider", "mock", "--model", "x"]) == 0
        payload = json.loads(capsys.readouterr().out)
        clouds = {m["name"]: m["cloud"] for m in payload["models"]}
        assert clouds["llama3:cloud"] is True
        assert clouds["llama3"] is False
        assert any(":cloud" in w for w in payload["warnings"])

    def test_doctor_warns_non_loopback_override(self, suites_root, capsys, monkeypatch):
        monkeypatch.setattr(
            "evalkit.cli.build_provider",
            lambda config: (_ for _ in ()).throw(AssertionError("not reached")),
        )

        # doctor prints the override warning BEFORE building the provider;
        # it must reach list_models, so use a stub provider instead.
        from evalkit.provider.mock import MockProvider

        monkeypatch.setattr(
            "evalkit.cli.build_provider", lambda config: MockProvider(model="m")
        )
        assert (
            main(
                [
                    "doctor",
                    "--provider",
                    "ollama",
                    "--base-url",
                    "http://203.0.113.7:11434",
                    "--allow-non-loopback",
                ]
            )
            == 0
        )
        out = capsys.readouterr().out
        assert "allow_non_loopback override is ACTIVE" in out


class TestReportAndCompare:
    def _make_run(self, suites_root, capsys, model="mock-model"):
        assert main(["run", "evidence_grounding", "--provider", "mock", "--model", model]) == 0
        out = capsys.readouterr().out
        run_id = [line for line in out.splitlines() if "stored:" in line][0]
        return run_id.split("stored:")[1].strip()

    def test_report_prints_markdown(self, suites_root, capsys):
        run_path = self._make_run(suites_root, capsys)
        assert main(["report", run_path]) == 0
        md = capsys.readouterr().out
        assert md.startswith("# EvalKit run")
        assert "Aggregate formula" in md

    def test_report_unknown_run_exits_one(self, suites_root, capsys):
        assert main(["report", "20260101T000000Z-ffffffff"]) == 1
        assert "error:" in capsys.readouterr().err

    def test_compare_two_runs(self, suites_root, capsys):
        run_a = self._make_run(suites_root, capsys)
        run_b = self._make_run(suites_root, capsys)
        assert main(["compare", run_a, run_b]) == 0
        out = capsys.readouterr().out
        assert "Comparing" in out
        assert "vs" in out

    def test_compare_mismatched_models_exits_one(self, suites_root, capsys):
        run_a = self._make_run(suites_root, capsys)
        run_b = self._make_run(suites_root, capsys)  # same model by fixture
        # Force a mismatch by rewriting run_b's config model.
        path_b = Path(run_b)
        payload = json.loads((path_b / "result.json").read_text(encoding="utf-8"))
        payload["model"] = "other-model"
        payload["config"]["model"] = "other-model"
        (path_b / "result.json").write_text(json.dumps(payload), encoding="utf-8")
        assert main(["compare", run_a, run_b]) == 1
        assert "error:" in capsys.readouterr().err


class TestBadPathsAndErrors:
    def test_bad_config_path_exits_one_clean(self, capsys, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        missing = tmp_path / "nope.json"
        # --config pointing at a nonexistent file: config loader must not
        # crash; load_config only reads it if it exists, so behaviour is
        # defaults. Point at a corrupt one instead.
        (tmp_path / "bad.json").write_text("{ not json", encoding="utf-8")
        assert main(["list", "--config", str(tmp_path / "bad.json")]) == 1
        err = capsys.readouterr().err
        assert "error:" in err
        assert "Traceback" not in err

    def test_runtime_errors_never_print_tracebacks(self, suites_root, capsys):
        main(["list", "--suite", "vibes"])
        assert "Traceback" not in capsys.readouterr().err

    def test_no_traceback_on_missing_suites(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        main(["run", "evidence_grounding", "--provider", "mock"])
        assert "Traceback" not in capsys.readouterr().err