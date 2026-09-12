"""Contract tests for the frozen provider interface (evalkit/provider/base.py).

These test the CONTRACT, not any specific provider implementation.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from evalkit.provider.base import (
    GenerationResult,
    ModelInfo,
    Provider,
    ProviderConnectionError,
    ProviderError,
    ProviderProtocolError,
    ProviderTimeout,
)


class TestErrorHierarchy:
    def test_provider_error_is_exception(self):
        assert issubclass(ProviderError, Exception)

    def test_connection_error_subclasses_provider_error(self):
        assert issubclass(ProviderConnectionError, ProviderError)

    def test_timeout_subclasses_provider_error(self):
        assert issubclass(ProviderTimeout, ProviderError)

    def test_connection_error_is_catchable_as_provider_error(self):
        with pytest.raises(ProviderError):
            raise ProviderConnectionError("refused")

    def test_timeout_is_catchable_as_provider_error(self):
        with pytest.raises(ProviderError):
            raise ProviderTimeout("too slow")

    def test_protocol_error_subclasses_provider_error(self):
        assert issubclass(ProviderProtocolError, ProviderError)

    def test_protocol_error_is_catchable_as_provider_error(self):
        with pytest.raises(ProviderError):
            raise ProviderProtocolError("bad body")


class TestGenerationResult:
    def test_required_fields_exist(self):
        field_names = {f.name for f in dataclasses.fields(GenerationResult)}
        assert {"text", "model", "provider", "elapsed_ms", "raw"} <= field_names

    def test_text_model_provider_elapsed_are_required(self):
        # All but `raw` must be positional-required (no default).
        required = {
            f.name
            for f in dataclasses.fields(GenerationResult)
            if f.default is dataclasses.MISSING
            and f.default_factory is dataclasses.MISSING
        }
        assert required == {"text", "model", "provider", "elapsed_ms"}

    def test_raw_defaults_to_empty_dict(self):
        result = GenerationResult(text="t", model="m", provider="p", elapsed_ms=1)
        assert result.raw == {}

    def test_raw_is_always_dict_not_none(self):
        # Contract: raw is never None; backends without metadata send {}.
        result = GenerationResult(text="t", model="m", provider="p", elapsed_ms=1, raw={})
        assert isinstance(result.raw, dict)

    def test_result_is_frozen(self):
        result = GenerationResult(text="t", model="m", provider="p", elapsed_ms=1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.text = "mutated"  # type: ignore[misc]

    def test_elapsed_ms_is_float(self):
        result = GenerationResult(text="t", model="m", provider="p", elapsed_ms=5.0)
        assert isinstance(result.elapsed_ms, float)
        assert not isinstance(result.elapsed_ms, bool)


class TestModelInfo:
    def test_name_required(self):
        info = ModelInfo(name="llama3")
        assert info.name == "llama3"
        assert info.size_bytes is None
        assert info.details == {}

    def test_frozen(self):
        info = ModelInfo(name="llama3")
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.name = "other"  # type: ignore[misc]


class TestProviderABC:
    def test_cannot_instantiate_abstract_provider(self):
        with pytest.raises(TypeError):
            Provider()  # type: ignore[abstract]

    def test_generate_signature_matches_contract(self):
        sig = inspect.signature(Provider.generate)
        params = list(sig.parameters)
        assert params == ["self", "prompt", "system", "options"]
        system = sig.parameters["system"]
        options = sig.parameters["options"]
        assert system.kind is inspect.Parameter.KEYWORD_ONLY
        assert options.kind is inspect.Parameter.KEYWORD_ONLY
        assert system.default is None
        assert options.default is None

    def test_generate_returns_generation_result_annotation(self):
        sig = inspect.signature(Provider.generate)
        assert sig.return_annotation in (
            GenerationResult,
            "GenerationResult",
            "evalkit.provider.base.GenerationResult",
        )

    def test_list_models_returns_list_annotation(self):
        sig = inspect.signature(Provider.list_models)
        origin = getattr(sig.return_annotation, "__origin__", None)
        assert origin is list or sig.return_annotation in ("list", "list[ModelInfo]")