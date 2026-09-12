"""Ollama backend over stdlib urllib. Loopback by default, no silent cloud.

Talks to the local Ollama HTTP API (default http://127.0.0.1:11434).
Only 127.0.0.1/localhost (and literal loopback IPs) are permitted by
design and this is rejected in code, not by convention; non-loopback
endpoints require the explicit allow_non_loopback=True override.

R7 posture (Amendment v0.1.3): every request sets an explicit timeout
mapped to ProviderTimeout; there are no retries in v0.1 (max 1 retry may
only arrive via explicit config in a later amendment — no retry storms);
models are never auto-pulled; there is no telemetry.

Security posture: no credential handling, no logging of prompt bodies,
nothing from responses is ever executed or shelled out. All failures
surface as the contract errors from base.py.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .base import (
    GenerationResult,
    ModelInfo,
    Provider,
    ProviderConnectionError,
    ProviderProtocolError,
    ProviderTimeout,
)

__all__ = ["OllamaProvider"]

_DEFAULT_BASE_URL = "http://127.0.0.1:11434"
_DEFAULT_TIMEOUT_S = 120.0
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        return socket.inet_pton(socket.AF_INET, host).startswith(b"\x7f") or socket.inet_pton(
            socket.AF_INET6, host.strip("[]")
        ) in (socket.inet_pton(socket.AF_INET6, "::1"),)
    except (OSError, ValueError):
        return False


class OllamaProvider(Provider):
    """Generate via POST /api/generate; discover models via GET /api/tags.

    allow_non_loopback=True is an explicit configuration override for
    non-loopback endpoints; construction explains the rule so nothing
    goes silent. Construction performs scheme + loopback checks ONLY:
    DNS failures (including unresolvable hosts under the override)
    surface at request time via the v0.1.6 error mapping, with the
    "is Ollama running?" hint. Malformed URLs (e.g. unbracketed
    IPv6 like "http://::1:11434") are rejected as non-loopback by
    design — fail-closed, even though the message says non-loopback
    rather than malformed. Note the
    boundary: EvalKit constrains the ENDPOINT (loopback), not the model
    tag — a ":cloud" model tag routes inference off-machine and is
    surfaced as a warning by Core's doctor/models commands.
    """

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = "",
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        allow_non_loopback: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/") or _DEFAULT_BASE_URL
        self._model = model
        self._timeout_s = timeout_s
        parsed = urlparse(self._base_url)
        if parsed.scheme != "http":
            raise ProviderConnectionError(
                f"refusing base URL with scheme {parsed.scheme!r}; "
                "EvalKit talks plain HTTP to a local Ollama (no TLS, no cloud)"
            )
        if not _is_loopback_host(parsed.hostname):
            if not allow_non_loopback:
                raise ProviderConnectionError(
                    f"refusing non-loopback Ollama base URL {self._base_url!r}: "
                    "EvalKit only talks to a local Ollama by default. "
                    "If you really mean a remote endpoint, set allow_non_loopback=True "
                    "in the provider config."
                )
        self._pinned_host = parsed.hostname or "127.0.0.1"

    @property
    def name(self) -> str:
        return "ollama"

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        options: dict | None = None,
    ) -> GenerationResult:
        if not self._model:
            raise ProviderConnectionError(
                "no model configured for OllamaProvider; pass model= or pick one "
                "from list_models()"
            )
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }
        if system is not None:
            payload["system"] = system
        if options:
            payload["options"] = options
        started = time.perf_counter()
        data = self._post_json("/api/generate", payload)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not isinstance(data, dict) or "response" not in data:
            raise ProviderProtocolError(
                "Ollama generate response missing 'response' field"
            )
        return GenerationResult(
            text=str(data["response"]),
            model=str(data.get("model", self._model)),
            provider=self.name,
            elapsed_ms=elapsed_ms,
            raw=data,
        )

    def list_models(self) -> list[ModelInfo]:
        data = self._get_json("/api/tags")
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise ProviderProtocolError(
                "Ollama /api/tags response missing 'models' list"
            )
        models: list[ModelInfo] = []
        for entry in data["models"]:
            if not isinstance(entry, dict) or "name" not in entry:
                raise ProviderProtocolError(
                    "Ollama /api/tags entry missing 'name' field"
                )
            details = entry.get("details") or {}
            models.append(
                ModelInfo(
                    name=str(entry["name"]),
                    size_bytes=entry.get("size"),
                    details=dict(details) if isinstance(details, dict) else {},
                )
            )
        return models

    def _post_json(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            self._base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._urlopen_json(request)

    def _get_json(self, path: str) -> dict:
        return self._urlopen_json(urllib.request.Request(self._base_url + path))

    def _urlopen_json(self, request: urllib.request.Request) -> dict:
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise ProviderConnectionError(
                f"Ollama returned HTTP {exc.code} for {request.full_url}"
            ) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            timedOut = isinstance(reason, (TimeoutError, socket.timeout))
            refused = isinstance(reason, ConnectionError) or (
                isinstance(reason, OSError)
                and getattr(reason, "errno", None) in (10061, 111, -1)
            )
            if refused:
                raise ProviderConnectionError(
                    f"nothing is listening at {self._base_url}: {reason}. "
                    "Is Ollama running? (try: ollama serve)"
                ) from exc
            if timedOut:
                raise ProviderTimeout(
                    f"Ollama at {self._base_url} did not answer within "
                    f"{self._timeout_s}s. Either nothing is listening there "
                    "(is Ollama running? try: ollama serve) or the model is "
                    "still loading; raise timeout_s if it is simply slow."
                ) from exc
            if isinstance(reason, OSError):
                raise ProviderConnectionError(
                    f"cannot reach Ollama at {self._base_url}: {reason}. "
                    "Is Ollama running? (try: ollama serve)"
                ) from exc
            raise ProviderConnectionError(
                f"cannot reach Ollama at {self._base_url}: {reason}"
            ) from exc
        except TimeoutError as exc:
            raise ProviderTimeout(f"Ollama timed out: {exc}") from exc
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderProtocolError(
                f"Ollama returned HTTP 200 with an unparseable body: {exc}"
            ) from exc