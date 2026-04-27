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


class OpenAIImageProvider(ImageProvider):
    MODEL = "dall-e-3"

    def __init__(self, api_key: str):
        self._api_key = api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def generate(self, prompt: str, **kwargs) -> ImageResult:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self._api_key)
            # Prepend safety framing — DALL-E 3 responds well to this
            safe_prompt = f"Children's book watercolor illustration, soft and warm, age-appropriate, no text. {prompt}"
            response = client.images.generate(
                model=self.MODEL,
                prompt=safe_prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            url = response.data[0].url
            return ImageResult(url=url)
        except Exception as exc:
            log.warning("OpenAI image generation failed: %s", exc)
            return ImageResult(url=None, error=str(exc))


class ReplicateProvider(ImageProvider):
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
            log.warning("Replicate image generation failed: %s", exc)
            return ImageResult(url=None, error=str(exc))


class NullImageProvider(ImageProvider):
    """Used when no provider is configured. Story renders text-only."""

    def is_configured(self) -> bool:
        return False

    def generate(self, prompt: str, **kwargs) -> ImageResult:
        return ImageResult(url=None, error="No image provider configured")


def cache_image_locally(url: str, cache_dir) -> str:
    """Download a remote image URL to local disk. Returns Flask static path.

    Falls back to the original URL if download fails so generation still works.
    """
    import hashlib
    import urllib.request
    from pathlib import Path

    try:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

        clean = url.split("?")[0].lower()
        ext   = "webp" if clean.endswith(".webp") else "png" if clean.endswith(".png") else "jpg"
        name  = hashlib.sha256(url.encode()).hexdigest()[:24] + "." + ext
        dest  = cache_dir / name

        if not dest.exists():
            urllib.request.urlretrieve(url, dest)

        return f"/static/img_cache/{name}"
    except Exception as exc:
        log.warning("Image local cache failed, using remote URL: %s", exc)
        return url


def get_image_provider(config) -> ImageProvider:
    """Factory — returns the configured provider.
    Accepts both Flask config dicts and plain config objects.
    Set IMAGE_PROVIDER to 'openai' or 'replicate' in your .env.
    """
    _get = (lambda k, d=None: config.get(k, d)) if isinstance(config, dict) else (lambda k, d=None: getattr(config, k, d))
    provider = _get("IMAGE_PROVIDER", "openai")
    if provider == "openai":
        api_key = _get("OPENAI_API_KEY", "") or ""
        if not api_key:
            return NullImageProvider()
        return OpenAIImageProvider(api_key=api_key)
    if provider == "replicate":
        api_key = _get("REPLICATE_API_KEY", "") or ""
        if not api_key:
            return NullImageProvider()
        return ReplicateProvider(api_key=api_key)
    return NullImageProvider()
