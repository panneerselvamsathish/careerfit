"""Builds the judge's LLM client from environment settings, plus a disk cache of answers.

Composition-root code, shared by cli.py (and later api.py). judge/ never reads the
environment or touches disk; it only receives an object with create().
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic

from careerfit.judge.scorer import JudgeFailure

# Bedrock default is the global cross-region inference profile, which is how this account is
# provisioned. Override with CAREERFIT_MODEL for a regional profile.
DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "bedrock": "global.anthropic.claude-opus-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMConfigError(Exception):
    pass


class SdkLLM:
    """Wraps an SDK create() so API failures surface as JudgeFailure, never as a traceback."""

    def __init__(self, create: Callable[..., Any]):
        self._create = create

    def create(self, **kwargs: Any) -> Any:
        try:
            return self._create(**kwargs)
        except anthropic.APIError as e:
            raise JudgeFailure(f"LLM request failed ({type(e).__name__}): {e}") from e


def make_llm(env: Mapping[str, str]) -> tuple[SdkLLM, str]:
    provider = env.get("CAREERFIT_LLM_PROVIDER", "anthropic").strip().lower()
    if provider not in DEFAULT_MODELS:
        raise LLMConfigError(f"CAREERFIT_LLM_PROVIDER must be one of {sorted(DEFAULT_MODELS)}, got {provider!r}")
    model = env.get("CAREERFIT_MODEL") or DEFAULT_MODELS[provider]
    try:
        if provider == "bedrock":
            region = env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION")
            if not region:
                raise LLMConfigError("CAREERFIT_LLM_PROVIDER=bedrock needs AWS_REGION to be set")
            # The bedrock-runtime client, not AnthropicBedrockMantle: the Mantle endpoint returned
            # 404 for every Opus 5.5 ID on this account, while bedrock-runtime serves it.
            return SdkLLM(anthropic.AnthropicBedrock(aws_region=region).messages.create), model
        client = anthropic.Anthropic()
    except anthropic.AnthropicError as e:
        raise LLMConfigError(f"could not create the {provider} client: {e}") from e

    def create_with_fallback(**kwargs: Any) -> Any:
        return client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)

    return SdkLLM(create_with_fallback), model


class CachingLLM:
    """Replays a stored answer when the exact same request was made before. Zero tokens."""

    def __init__(self, inner: Any, directory: Path):
        self.inner = inner
        self.directory = directory

    def create(self, **kwargs: Any) -> Any:
        key = hashlib.sha256(json.dumps(kwargs, sort_keys=True, default=_jsonable).encode()).hexdigest()
        path = self.directory / f"{key}.json"
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            return SimpleNamespace(stop_reason=stored["stop_reason"], content=stored["content"])
        response = self.inner.create(**kwargs)
        if getattr(response, "stop_reason", None) == "end_turn":
            text_blocks = [{"type": "text", "text": b.text} for b in response.content if getattr(b, "type", None) == "text"]
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"stop_reason": "end_turn", "content": text_blocks}), encoding="utf-8")
        return response


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, SimpleNamespace):
        return vars(value)
    return str(value)
