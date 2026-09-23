"""Who runs the recap prompt.

``OpenAIProvider`` (``OPENAI_API_KEY``) serves the default model;
``AnthropicProvider`` (``ANTHROPIC_API_KEY``, or an ``ant auth login``
profile) serves ``claude-*``. ``make_provider`` picks by model name. Both
run the same prompt and schema; the default came from a comparison of
models over a 15-hour playthrough.
The ``RecapProvider`` protocol is the seam for a hosted proxy later: same
prompt, same schema, different transport. Only the compacted text
transcript is ever sent — never a frame.
"""

from __future__ import annotations

import os
import re
from typing import Protocol

from .schema import SessionRecap, Usage

DEFAULT_MODEL = "gpt-5.4-mini"
MODEL_ENV = "PREVIOUSLY_ON_MODEL"
# The JSON is ~3-4k tokens, but on models that think by default (Sonnet 5,
# Opus 5) the thinking counts against the same budget: chunk 1 of the
# playthrough spent 7.3k with 8k allowed and chunk 2 was cut off mid-string.
# Medium effort keeps that thinking short; Haiku 4.5 does not think unless
# asked and rejects the effort parameter altogether.
MAX_TOKENS = 16000
EFFORT_ENV = "PREVIOUSLY_ON_EFFORT"  # low | medium | high; models that think
DEFAULT_EFFORT = "medium"


def _output_config(model: str) -> dict | None:
    return None if "haiku" in model else {"effort": os.environ.get(EFFORT_ENV) or DEFAULT_EFFORT}


def default_model() -> str:
    return os.environ.get(MODEL_ENV) or DEFAULT_MODEL


class RecapError(RuntimeError):
    """Something the caller can print and move on from; the session log is safe."""


class RecapProvider(Protocol):
    model: str

    def generate(self, system: str, user: str) -> tuple[SessionRecap, Usage]: ...


class AnthropicProvider:
    def __init__(self, model: str | None = None) -> None:
        import anthropic

        self.model = model or default_model()
        try:
            self._client = anthropic.Anthropic()
        except anthropic.AnthropicError as exc:  # a named profile that does not exist, an unreadable config
            raise RecapError(f"credentials are misconfigured: {exc}") from exc

    @property
    def has_credentials(self) -> bool:
        return bool(self._client.auth_headers)

    def generate(self, system: str, user: str) -> tuple[SessionRecap, Usage]:
        import anthropic
        import pydantic

        try:
            extra = {"output_config": cfg} if (cfg := _output_config(self.model)) else {}
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_format=SessionRecap,
                **extra,
            )
        except pydantic.ValidationError as exc:
            # ``parse`` validates before we can look at stop_reason; a cut-off
            # JSON string is by far the likeliest cause.
            raise RecapError(f"the recap did not parse (cut off at max_tokens?): {str(exc).splitlines()[-1]}") from exc
        except anthropic.AuthenticationError as exc:
            raise RecapError(f"the API rejected the credentials (set ANTHROPIC_API_KEY): {exc.message}") from exc
        except anthropic.RateLimitError as exc:
            raise RecapError(f"rate limited; try again later: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise RecapError(f"API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise RecapError(f"could not reach the API: {exc}") from exc
        if response.stop_reason == "refusal":
            raise RecapError("the model declined to write this recap")
        if response.stop_reason == "max_tokens":
            raise RecapError("the recap was cut off (max_tokens); the transcript may be too long")
        recap = response.parsed_output
        if recap is None:
            raise RecapError("the model returned no parsable recap")
        u = response.usage
        usage = Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_input_tokens=u.cache_read_input_tokens or 0,
            cache_creation_input_tokens=u.cache_creation_input_tokens or 0,
        )
        return recap, usage


_OPENAI_MODEL = re.compile(r"^(gpt-|o\d)")
_OPENAI_REASONING = re.compile(r"^(gpt-5|o\d)")  # models that take reasoning.effort


class OpenAIProvider:
    """Same prompt and schema through OpenAI's Responses API, for comparisons."""

    def __init__(self, model: str) -> None:
        import openai

        self.model = model
        try:
            self._client = openai.OpenAI()
        except openai.OpenAIError:  # no key anywhere; the client refuses to exist
            self._client = None

    @property
    def has_credentials(self) -> bool:
        return self._client is not None and bool(self._client.api_key)

    def generate(self, system: str, user: str) -> tuple[SessionRecap, Usage]:
        import openai
        import pydantic

        if self._client is None:
            raise RecapError("no API credentials: set OPENAI_API_KEY")
        extra = {"reasoning": {"effort": "low"}} if _OPENAI_REASONING.match(self.model) else {}
        try:
            response = self._client.responses.parse(
                model=self.model,
                instructions=system,
                input=user,
                max_output_tokens=MAX_TOKENS,
                text_format=SessionRecap,
                **extra,
            )
        except pydantic.ValidationError as exc:
            raise RecapError(f"the recap did not parse (cut off at max_output_tokens?): {str(exc).splitlines()[-1]}") from exc
        except openai.AuthenticationError as exc:
            raise RecapError(f"the API rejected the credentials (set OPENAI_API_KEY): {exc.message}") from exc
        except openai.RateLimitError as exc:
            raise RecapError(f"rate limited; try again later: {exc.message}") from exc
        except openai.APIStatusError as exc:
            raise RecapError(f"API error {exc.status_code}: {exc.message}") from exc
        except openai.APIConnectionError as exc:
            raise RecapError(f"could not reach the API: {exc}") from exc
        if response.status == "incomplete":
            reason = response.incomplete_details.reason if response.incomplete_details else "unknown"
            raise RecapError(f"the recap was cut off ({reason})")
        recap = response.output_parsed
        if recap is None:
            raise RecapError("the model returned no parsable recap")
        u = response.usage
        cached = u.input_tokens_details.cached_tokens if u and u.input_tokens_details else 0
        usage = Usage(
            input_tokens=(u.input_tokens if u else 0) - cached,
            output_tokens=u.output_tokens if u else 0,
            cache_read_input_tokens=cached,
        )
        return recap, usage


def make_provider(model: str | None = None) -> AnthropicProvider | OpenAIProvider:
    model = model or default_model()
    return OpenAIProvider(model) if _OPENAI_MODEL.match(model) else AnthropicProvider(model)


def has_credentials() -> bool:
    """Cheap check before offering to summarise: is there anything to call with?"""
    try:
        return make_provider().has_credentials
    except RecapError:
        return False


class FakeProvider:
    """Returns a canned recap; records what it was asked. For tests."""

    model = "fake"

    def __init__(self, recap: SessionRecap) -> None:
        self.recap = recap
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> tuple[SessionRecap, Usage]:
        self.calls.append((system, user))
        return self.recap.model_copy(deep=True), Usage(input_tokens=len(user) // 4, output_tokens=100)
