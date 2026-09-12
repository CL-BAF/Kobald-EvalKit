"""Configuration loading and provider selection.

Config precedence (lowest to highest): built-in defaults, config file
(evalkit.json in the project root or --config), CLI flags. The
allow_non_loopback override is deliberately NOT settable via environment
variable (v0.1.6 Reviewer bar d): enabling off-machine endpoints requires
named intent in a config file or an explicit CLI flag.

The config snapshot recorded into RunRecord.config contains only
sanitized values: the base URL as configured (no credential material by
construction), options, suite list and versions — never secrets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError
from .provider import (
    MockProvider,
    OllamaProvider,
    Provider,
    ProviderConnectionError,
)

__all__ = ["SUPPORTED_PROVIDERS", "EvalKitConfig", "DEFAULT_BASE_URL", "load_config"]

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
SUPPORTED_PROVIDERS = ("mock", "ollama")
SUITES_DIR_NAME = "suites"
RUNS_DIR_NAME = "runs"
DEFAULT_TIMEOUT_S = 120.0
CLOUD_MODEL_SUFFIX = ":cloud"


@dataclass(frozen=True)
class EvalKitConfig:
    """Resolved configuration for one EvalKit invocation."""

    provider: str = "mock"
    model: str = ""
    base_url: str = DEFAULT_BASE_URL
    timeout_s: float = DEFAULT_TIMEOUT_S
    allow_non_loopback: bool = False
    options: dict = field(default_factory=dict)
    suites_dir: Path = field(default_factory=lambda: Path(SUITES_DIR_NAME))
    runs_dir: Path = field(default_factory=lambda: Path(RUNS_DIR_NAME))
    source_files: tuple[str, ...] = ()

    def snapshot(self, *, suites: list[str], evalkit_version: str, start_time_utc: str) -> dict:
        """R5 config snapshot for RunRecord (sanitized, compare-ready)."""
        return {
            "model": self.model,
            "provider": self.provider,
            "base_url": self.base_url,
            "options": dict(self.options),
            "suites": list(suites),
            "evalkit_version": evalkit_version,
            "start_time_utc": start_time_utc,
        }


def _deep_merge(base: dict, extra: dict) -> dict:
    merged = dict(base)
    for key, value in extra.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_file_layer(partial: dict, source: str) -> None:
    if not isinstance(partial, dict):
        raise ConfigError(f"{source}: top level must be a JSON object")
    if "provider" in partial:
        _check_provider_name(partial["provider"], source)
    if "base_url" in partial:
        _check_base_url_type(partial["base_url"], source)
    if "model" in partial:
        _check_model(partial["model"], source)
    if "timeout_s" in partial:
        _check_timeout(partial["timeout_s"], source)
    if "allow_non_loopback" in partial:
        _check_bool(partial["allow_non_loopback"], "allow_non_loopback", source)
    if "options" in partial:
        _check_options(partial["options"], source)


def _check_provider_name(value: object, source: str) -> None:
    if not isinstance(value, str) or value not in SUPPORTED_PROVIDERS:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        raise ConfigError(
            f"{source}: unknown provider {value!r} (supported: {supported})"
        )


def _check_base_url_type(value: object, source: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{source}: base_url must be a non-empty string")


def _check_model(value: object, source: str) -> None:
    if not isinstance(value, str):
        raise ConfigError(f"{source}: model must be a string")


def _check_timeout(value: object, source: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{source}: timeout_s must be a positive number")


def _check_bool(value: object, key: str, source: str) -> None:
    if not isinstance(value, bool):
        raise ConfigError(f"{source}: {key} must be a boolean")


def _check_options(value: object, source: str) -> None:
    if not isinstance(value, dict):
        raise ConfigError(f"{source}: options must be a JSON object")


def load_config(
    *,
    config_path: Path | None = None,
    cli_overrides: dict | None = None,
) -> EvalKitConfig:
    """Load evalkit.json (when present) and apply CLI overrides.

    Unknown keys in a config file raise ConfigError naming the file
    (typo safety, consistent with the case loader). CLI overrides use the
    same key names.
    """
    allowed_keys = {
        "provider",
        "model",
        "base_url",
        "timeout_s",
        "allow_non_loopback",
        "options",
        "suites_dir",
        "runs_dir",
    }
    merged: dict = {}
    sources: list[str] = []

    path = config_path or Path("evalkit.json")
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path}: invalid JSON ({exc})") from exc
        _apply_file_layer(data, str(path))
        unknown = set(data) - allowed_keys
        if unknown:
            raise ConfigError(
                f"{path}: unknown config key(s) {sorted(unknown)}; "
                f"allowed keys: {sorted(allowed_keys)}"
            )
        merged = _deep_merge(merged, data)
        sources.append(str(path))

    overrides = cli_overrides or {}
    unknown_overrides = set(overrides) - allowed_keys
    if unknown_overrides:
        raise ConfigError(f"unknown CLI override key(s): {sorted(unknown_overrides)}")
    filtered = {k: v for k, v in overrides.items() if v is not None}
    _apply_file_layer(filtered, "CLI overrides")
    merged = _deep_merge(merged, filtered)

    suites_dir = merged.get("suites_dir", SUITES_DIR_NAME)
    runs_dir = merged.get("runs_dir", RUNS_DIR_NAME)
    if not isinstance(suites_dir, str) or not suites_dir:
        raise ConfigError("suites_dir must be a non-empty string")
    if not isinstance(runs_dir, str) or not runs_dir:
        raise ConfigError("runs_dir must be a non-empty string")

    return EvalKitConfig(
        provider=merged.get("provider", "mock"),
        model=merged.get("model", ""),
        base_url=merged.get("base_url", DEFAULT_BASE_URL),
        timeout_s=merged.get("timeout_s", DEFAULT_TIMEOUT_S),
        allow_non_loopback=merged.get("allow_non_loopback", False),
        options=dict(merged.get("options", {})),
        suites_dir=Path(suites_dir),
        runs_dir=Path(runs_dir),
        source_files=tuple(sources),
    )


def build_provider(config: EvalKitConfig) -> Provider:
    """Factory wiring for the configured provider.

    Provider-specific options (allow_non_loopback, timeout) live here in
    Core's config layer, keeping evalkit/provider dependency-free
    (v0.1.4 ruling). No environment variable can flip allow_non_loopback:
    only config file or explicit CLI intent reaches this code.
    """
    if config.provider == "mock":
        return MockProvider(model=config.model or "mock-model")
    if config.provider == "ollama":
        try:
            return OllamaProvider(
                base_url=config.base_url,
                model=config.model,
                timeout_s=config.timeout_s,
                allow_non_loopback=config.allow_non_loopback,
            )
        except ProviderConnectionError as exc:
            raise ConfigError(str(exc)) from exc
    raise ConfigError(f"unknown provider {config.provider!r}")


def is_cloud_model(model_name: str) -> bool:
    """v0.1.4: ':cloud' tags route inference off-machine; surfaced as data."""
    return model_name.endswith(CLOUD_MODEL_SUFFIX)