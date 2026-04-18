"""
Image provider abstraction — mirrors ai_provider.py.

Add on-device diffusion providers here later.
Never ship a default API key — parent must configure in settings.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class ImageResult:
    url: Optional[str]
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.url is not None


class ImageProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> ImageResult:
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        ...


class ReplicateProvider(ImageProvider):
    # Flux Schnell: fast, cheap, child-safe with appropriate prompting
    MODEL = "black-forest-labs/flux-schnell"

    def __init__(self, api_key: str):
        self._api_key = api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def generate(self, prompt: str, **kwargs) -> ImageResult:
        try:
            import replicate
            client = replicate.Client(api_token=self._api_key)
            output = client.run(
                self.MODEL,
                input={
                    "prompt": prompt,
                    "aspect_ratio": "4:3",
                    "output_format": "webp",
                    "go_fast": True,
                    "num_outputs": 1,
                },
            )
            if output:
                return ImageResult(url=str(output[0]))
            return ImageResult(url=None, error="No output from provider")
        except Exception as exc:
            log.warning("Image generation failed: %s", exc)
            return ImageResult(url=None, error=str(exc))


class NullImageProvider(ImageProvider):
    """Used when no provider is configured. Story renders text-only."""

    def is_configured(self) -> bool:
        return False

    def generate(self, prompt: str, **kwargs) -> ImageResult:
        return ImageResult(url=None, error="No image provider configured")


def get_image_provider(config) -> ImageProvider:
    """Factory — returns the configured provider."""
    provider = getattr(config, "IMAGE_PROVIDER", "replicate")
    if provider == "replicate":
        api_key = getattr(config, "REPLICATE_API_KEY", "")
        if not api_key:
            return NullImageProvider()
        return ReplicateProvider(api_key=api_key)
    return NullImageProvider()
