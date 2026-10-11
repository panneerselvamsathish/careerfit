"""The Anthropic SDK adapter: the only place the SDK is constructed and called.

The composition root passes in its environment mapping; this module never reads os.environ
itself and never touches disk.
"""

from collections.abc import Callable, Mapping
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
