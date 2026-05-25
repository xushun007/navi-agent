from __future__ import annotations

from navi_agent.config import ModelSettings

from .transports import ModelTransport, OpenAICompatibleTransport


def build_transport(settings: ModelSettings) -> ModelTransport:
    if settings.provider != "openai_compatible":
        raise ValueError(f"Unsupported model provider: {settings.provider}")
    if not settings.api_key:
        raise ValueError("Missing API key for openai_compatible transport")

    return OpenAICompatibleTransport(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
    )
