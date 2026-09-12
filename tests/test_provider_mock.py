"""Tests for MockProvider: determinism, scripting, failure injection.

Also guards the offline promise: no socket may be created while the
mock serves responses.
"""

from __future__ import annotations

import socket

import pytest

from evalkit.provider.base import (
    GenerationResult,
    ProviderConnectionError,
    ProviderError,
    ProviderProtocolError,
    ProviderTimeout,
)
from evalkit.provider.mock import MockProvider, ScriptedResponse


@pytest.fixture()
def no_network(monkeypatch):
    """Fail loudly if anything in the test tries to open a socket."""

    def _blocked(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("network access attempted during offline test")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


class TestScriptedResponses:
    def test_fallback_text_when_no_match(self, no_network):
        provider = MockProvider(fallback_text="nothing matched")
        result = provider.generate("totally unrelated prompt")
        assert result.text == "nothing matched"

    def test_first_matching_script_wins(self, no_network):
        provider = MockProvider(
            responses=[
                ScriptedResponse(match="alpha", text="alpha reply"),
                ScriptedResponse(match="beta", text="beta reply"),
                ScriptedResponse(match="alpha", text="second alpha reply"),
            ]
        )
        result = provider.generate("prompt with alpha and beta")
        assert result.text == "alpha reply"

    def test_dict_responses_form(self, no_network):
        provider = MockProvider(responses={"evidence": "grounded answer"})
        assert provider.generate("prompt with evidence").text == "grounded answer"
        assert provider.generate("unrelated").text == ""

    def test_match_requires_substring(self, no_network):
        provider = MockProvider(
            responses=[ScriptedResponse(match="ALPHA", text="upper reply")]
        )
        result = provider.generate("prompt with alpha")
        assert result.text == ""  # case-sensitive miss -> fallback

    def test_determinism_same_prompt_same_result(self, no_network):
        provider = MockProvider(
            responses=[ScriptedResponse(match="case1", text="stable reply")]
        )
        first = provider.generate("case1 prompt")
        second = provider.generate("case1 prompt")
        assert first == second

    def test_empty_fallback_default(self, no_network):
        provider = MockProvider()
        assert provider.generate("anything").text == ""


class TestGenerationResultShape:
    def test_result_fields(self, no_network):
        provider = MockProvider(
            model="mock-model",
            responses=[ScriptedResponse(match="x", text="hello")],
            latency_ms=12.5,
        )
        result = provider.generate("x prompt")
        assert isinstance(result, GenerationResult)
        assert result.text == "hello"
        assert result.model == "mock-model"
        assert result.provider == "mock"
        assert result.elapsed_ms == 12.5
        assert isinstance(result.elapsed_ms, float)

    def test_per_entry_elapsed_ms_override(self, no_network):
        provider = MockProvider(
            responses=[ScriptedResponse(match="slow", text="...", elapsed_ms=500.5)],
            latency_ms=1.0,
        )
        assert provider.generate("slow prompt").elapsed_ms == 500.5
        assert provider.generate("unrelated").elapsed_ms == 1.0

    def test_provider_name_is_mock(self, no_network):
        assert MockProvider().name == "mock"

    def test_raw_passthrough(self, no_network):
        provider = MockProvider(raw={"finish_reason": "stop"})
        result = provider.generate("prompt")
        assert result.raw == {"finish_reason": "stop"}

    def test_raw_default_empty_dict(self, no_network):
        result = MockProvider().generate("prompt")
        assert result.raw == {}


class TestSystemAndOptionsPassthrough:
    def test_system_and_options_recorded(self, no_network):
        provider = MockProvider()
        provider.generate("p", system="be terse", options={"temperature": 0.2})
        assert provider.calls == [
            {"prompt": "p", "system": "be terse", "options": {"temperature": 0.2}}
        ]

    def test_calls_accumulate_in_order(self, no_network):
        provider = MockProvider()
        provider.generate("one")
        provider.generate("two")
        assert [c["prompt"] for c in provider.calls] == ["one", "two"]


class TestFailureInjection:
    def test_fail_with_raises_exact_instance(self, no_network):
        err = ProviderConnectionError("connection refused")
        provider = MockProvider(fail_with=err)
        with pytest.raises(ProviderConnectionError) as excinfo:
            provider.generate("prompt")
        assert excinfo.value is err

    def test_fail_with_timeout_subclass(self, no_network):
        provider = MockProvider(fail_with=ProviderTimeout("took too long"))
        with pytest.raises(ProviderError):
            provider.generate("prompt")

    def test_fail_with_protocol_error(self, no_network):
        err = ProviderProtocolError("bad body")
        provider = MockProvider(fail_with=err)
        with pytest.raises(ProviderProtocolError) as excinfo:
            provider.generate("prompt")
        assert excinfo.value is err

    def test_per_entry_fail_with(self, no_network):
        err = ProviderProtocolError("entry-level protocol failure")
        provider = MockProvider(
            responses=[ScriptedResponse(match="broken", fail_with=err)],
            fallback_text="fine here",
        )
        with pytest.raises(ProviderProtocolError) as excinfo:
            provider.generate("a broken prompt")
        assert excinfo.value is err
        # Unmatched prompts still get the fallback.
        assert provider.generate("healthy prompt").text == "fine here"

    def test_failed_call_still_recorded(self, no_network):
        provider = MockProvider(fail_with=ProviderConnectionError("down"))
        with pytest.raises(ProviderConnectionError):
            provider.generate("prompt")
        assert len(provider.calls) == 1


class TestModelListing:
    def test_lists_configured_model(self, no_network):
        provider = MockProvider(model="mock-model")
        models = provider.list_models()
        assert [m.name for m in models] == ["mock-model"]

    def test_model_info_shape(self, no_network):
        (info,) = MockProvider(model="m1").list_models()
        assert info.size_bytes is None
        assert info.details.get("provider") == "mock"