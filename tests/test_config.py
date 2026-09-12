"""Config contract tests: precedence, validation, provider factory wiring,
and the security pin that allow_non_loopback is never env-settable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalkit.config import (
    DEFAULT_BASE_URL,
    EvalKitConfig,
    build_provider,
    is_cloud_model,
    load_config,
)
from evalkit.errors import ConfigError
from evalkit.provider.mock import MockProvider


class TestDefaults:
    def test_default_config(self):
        config = load_config()
        assert config.provider == "mock"
        assert config.model == ""
        assert config.base_url == DEFAULT_BASE_URL == "http://127.0.0.1:11434"
        assert config.allow_non_loopback is False
        assert config.options == {}

    def test_snapshot_shape(self):
        config = EvalKitConfig(provider="mock", model="m")
        snapshot = config.snapshot(
            suites=["s"], evalkit_version="0.2.0", start_time_utc="t"
        )
        assert set(snapshot) == {
            "model",
            "provider",
            "base_url",
            "options",
            "suites",
            "evalkit_version",
            "start_time_utc",
        }
        assert snapshot["suites"] == ["s"]


class TestPrecedence:
    def test_file_overrides_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "evalkit.json").write_text(
            json.dumps({"provider": "ollama", "model": "llama3"}), encoding="utf-8"
        )
        config = load_config()
        assert config.provider == "ollama"
        assert config.model == "llama3"

    def test_cli_overrides_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "evalkit.json").write_text(
            json.dumps({"provider": "ollama", "model": "file-model"}), encoding="utf-8"
        )
        config = load_config(cli_overrides={"provider": "mock", "model": "cli-model"})
        assert config.provider == "mock"
        assert config.model == "cli-model"

    def test_none_overrides_ignored(self, tmp_path):
        (tmp_path / "evalkit.json").write_text(
            json.dumps({"provider": "ollama"}), encoding="utf-8"
        )
        config = load_config(
            config_path=tmp_path / "evalkit.json", cli_overrides={"provider": None}
        )
        assert config.provider == "ollama"

    def test_explicit_config_path(self, tmp_path):
        custom = tmp_path / "custom.json"
        custom.write_text(json.dumps({"model": "custom-model"}), encoding="utf-8")
        config = load_config(config_path=custom)
        assert config.model == "custom-model"

    def test_deep_merge_options(self, tmp_path):
        custom = tmp_path / "options.json"
        custom.write_text(
            json.dumps(
                {
                    "options": {"temperature": 0.2, "top_k": 40},
                }
            ),
            encoding="utf-8",
        )
        config = load_config(config_path=custom, cli_overrides={"options": {"temperature": 0.9}})
        assert config.options == {"temperature": 0.9, "top_k": 40}


class TestValidation:
    def test_unknown_config_key_rejected(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"providor": "mock"}), encoding="utf-8")
        with pytest.raises(ConfigError) as excinfo:
            load_config(config_path=bad)
        assert "providor" in str(excinfo.value)

    def test_unknown_provider_rejected(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"provider": "vibes"}), encoding="utf-8")
        with pytest.raises(ConfigError) as excinfo:
            load_config(config_path=bad)
        assert "vibes" in str(excinfo.value)

    def test_invalid_json_rejected(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(config_path=bad)

    def test_non_object_top_level_rejected(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("[1, 2]", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(config_path=bad)

    def test_bad_timeout_rejected(self, tmp_path):
        for value in (0, -1, "10", True):
            bad = tmp_path / "bad.json"
            bad.write_text(json.dumps({"timeout_s": value}), encoding="utf-8")
            with pytest.raises(ConfigError):
                load_config(config_path=bad)

    def test_non_bool_allow_non_loopback_rejected(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"allow_non_loopback": "yes"}), encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(config_path=bad)

    def test_non_dict_options_rejected(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"options": [1]}), encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(config_path=bad)

    def test_empty_dirs_strings_rejected(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"suites_dir": ""}), encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(config_path=bad)


class TestSecurityPins:
    def test_allow_non_loopback_not_env_settable(self, monkeypatch):
        # v0.1.6 Reviewer bar: the override must require named intent in a
        # config file or CLI override — NO environment variable may set it.
        monkeypatch.setenv("EVALKIT_ALLOW_NON_LOOPBACK", "1")
        monkeypatch.setenv("ALLOW_NON_LOOPBACK", "1")
        config = load_config()
        assert config.allow_non_loopback is False

    def test_allow_non_loopback_via_config_file(self, tmp_path):
        ok = tmp_path / "ok.json"
        ok.write_text(json.dumps({"allow_non_loopback": True}), encoding="utf-8")
        config = load_config(config_path=ok)
        assert config.allow_non_loopback is True

    def test_allow_non_loopback_via_cli_override(self):
        config = load_config(cli_overrides={"allow_non_loopback": True})
        assert config.allow_non_loopback is True

    def test_cli_override_true_only_when_truthy(self):
        # cli.py passes True only when the flag is given; None must not flip.
        config = load_config(cli_overrides={"allow_non_loopback": None})
        assert config.allow_non_loopback is False

    def test_snapshot_carries_no_secrets(self, tmp_path):
        ok = tmp_path / "ok.json"
        ok.write_text(
            json.dumps(
                {
                    "provider": "ollama",
                    "model": "llama3",
                    "base_url": "http://127.0.0.1:11434",
                    "options": {"temperature": 0.5},
                }
            ),
            encoding="utf-8",
        )
        config = load_config(config_path=ok)
        snapshot = config.snapshot(suites=["s"], evalkit_version="v", start_time_utc="t")
        assert "password" not in json.dumps(snapshot).lower()
        assert "authorization" not in json.dumps(snapshot).lower()


class TestBuildProvider:
    def test_mock_provider_built(self):
        provider = build_provider(EvalKitConfig(provider="mock", model="my-mock"))
        assert isinstance(provider, MockProvider)
        assert provider.name == "mock"
        assert provider.list_models()[0].name == "my-mock"

    def test_mock_model_default(self):
        provider = build_provider(EvalKitConfig(provider="mock"))
        assert provider.list_models()[0].name == "mock-model"

    def test_ollama_loopback_accepted(self):
        provider = build_provider(EvalKitConfig(provider="ollama", model="llama3"))
        assert provider.name == "ollama"

    def test_ollama_non_loopback_without_override_rejected(self):
        with pytest.raises(ConfigError) as excinfo:
            build_provider(
                EvalKitConfig(provider="ollama", model="m", base_url="http://203.0.113.7:11434")
            )
        assert "non-loopback" in str(excinfo.value)

    def test_unknown_provider_rejected(self):
        with pytest.raises(ConfigError):
            build_provider(EvalKitConfig(provider="vibes"))


class TestCloudModelFlag:
    def test_cloud_suffix_detected(self):
        assert is_cloud_model("llama3:cloud") is True
        assert is_cloud_model("llama3") is False
        assert is_cloud_model("cloud") is False
        assert is_cloud_model("a:cloud") is True