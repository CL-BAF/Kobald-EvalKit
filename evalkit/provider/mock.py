"""Deterministic offline provider for tests and dry runs.

Never touches the network. Responses come from scripted patterns
(prompt-substring matches plus a fallback) and are fully injectable so
Tests can drive valid, malformed, citation-inventing and JSON-breaking
scenarios without a server. No randomness unless seeded via latency_ms
spread; iteration order is always construction order.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import (
    GenerationResult,
    ModelInfo,
    Provider,
    ProviderError,
    ProviderProtocolError,
)

__all__ = ["ScriptedResponse", "MockProvider"]


@dataclass(frozen=True)
class ScriptedResponse:
    """A canned reply served when the prompt contains `match`.

    text is served as a normal completion. fail_with raises that
    ProviderError instead of producing text (e.g. ProviderProtocolError
    for malformed backend bodies). elapsed_ms overrides the provider
    default latency for this entry.
    """

    match: str
    text: str = ""
    fail_with: ProviderError | None = None
    elapsed_ms: float | None = None


class MockProvider(Provider):
    """Offline stand-in with deterministic output.

    Injection protocol (agreed with Tests, no monkeypatching needed):
    construct with `responses` as either an ordered list of
    ScriptedResponse (first match wins, checked in construction order)
    or a plain dict mapping a prompt-substring to the reply text, e.g.
    MockProvider(responses={"evidence": "grounded answer"}).
    Everything unmatched gets fallback_text.
    """

    def __init__(
        self,
        *,
        model: str = "mock-model",
        responses: list[ScriptedResponse] | dict[str, str] | None = None,
        fallback_text: str = "",
        latency_ms: float = 0.0,
        fail_with: ProviderError | None = None,
        raw: dict | None = None,
    ) -> None:
        self._model = model
        if responses is None:
            self._responses: list[ScriptedResponse] = []
        elif isinstance(responses, dict):
            self._responses = [
                ScriptedResponse(match=key, text=value) for key, value in responses.items()
            ]
        else:
            self._responses = list(responses)
        self._fallback_text = fallback_text
        self._latency_ms = float(latency_ms)
        self._fail_with = fail_with
        self._raw = raw if raw is not None else {}
        self.calls: list[dict] = []

    @property
    def name(self) -> str:
        return "mock"

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        options: dict | None = None,
    ) -> GenerationResult:
        self.calls.append({"prompt": prompt, "system": system, "options": options})
        if self._fail_with is not None:
            raise self._fail_with
        for scripted in self._responses:
            if scripted.match in prompt:
                if scripted.fail_with is not None:
                    raise scripted.fail_with
                entry_latency = (
                    self._latency_ms if scripted.elapsed_ms is None else float(scripted.elapsed_ms)
                )
                return GenerationResult(
                    text=scripted.text,
                    model=self._model,
                    provider=self.name,
                    elapsed_ms=entry_latency,
                    raw=dict(self._raw),
                )
        return GenerationResult(
            text=self._fallback_text,
            model=self._model,
            provider=self.name,
            elapsed_ms=self._latency_ms,
            raw=dict(self._raw),
        )

    def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(name=self._model, size_bytes=None, details={"provider": "mock"})]