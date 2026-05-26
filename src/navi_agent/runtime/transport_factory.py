from __future__ import annotations

from navi_agent.config import ModelSettings
from navi_agent.paths import get_config_path

from .transports import ModelTransport, OpenAICompatibleTransport


def build_transport(settings: ModelSettings) -> ModelTransport:
    if not settings.api_key:
        raise ValueError(
            "Missing API key for openai_compatible transport. "
            f"Set NAVI_API_KEY/OPENAI_API_KEY or configure model.api_key in {get_config_path()}"
        )

    return OpenAICompatibleTransport(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
    )
