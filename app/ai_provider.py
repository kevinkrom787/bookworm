"""
AI provider abstraction.

Add on-device providers here later — swap by setting config.AI_PROVIDER.
"""
from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod
from typing import Optional


class AIProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        """Return the model's text response."""


class ClaudeProvider(AIProvider):
    MODEL = "claude-sonnet-4-6"

    def __init__(self, api_key: str):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        msg = self._client.messages.create(
            model=self.MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            timeout=60.0,  # 60s hard timeout — fail fast rather than hang
        )
        return msg.content[0].text.strip()


class OllamaVocabEnricher:
    """Enriches story words with phonetics, definitions, and examples via a local Ollama model."""

    _AGE_BAND_AGES = {
        "seedlings":    "5-6",
        "explorers":    "7-9",
        "adventurers":  "10-12",
    }

    def __init__(self, base_url: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._model = model

    def enrich(self, word: str, age_band: str = "explorers", story_title: str = "") -> dict:
        """Returns {phonetic, definition, example}. Falls back to empty strings on any error."""
        age = self._AGE_BAND_AGES.get(age_band, "7-9")
        context = f' from the story "{story_title}"' if story_title else ""
        prompt = (
            f'Define the word "{word}" for a {age}-year-old child{context}. '
            f'Return a JSON object with exactly these three keys: '
            f'"phonetic" (IPA pronunciation in forward slashes, e.g. /wɜːrd/), '
            f'"definition" (one simple sentence a child would understand), '
            f'"example" (one fun sentence using the word).'
        )

        # Try /api/chat with format:"json" first (Ollama >=0.1.9)
        result = self._try_chat(prompt)
        if result:
            return result

        # Older Ollama: fall back to /api/generate with manual JSON extraction
        result = self._try_generate(prompt)
        if result:
            return result

        return {"phonetic": "", "definition": "", "example": ""}

    def _try_chat(self, prompt: str) -> Optional[dict]:
        import logging
        log = logging.getLogger(__name__)
        try:
            payload = json.dumps({
                "model":    self._model,
                "messages": [{"role": "user", "content": prompt}],
                "stream":   False,
                "format":   "json",
            }).encode()
            req = urllib.request.Request(
                f"{self._base_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read())
            text = data.get("message", {}).get("content", "").strip()
            log.debug("Ollama /api/chat raw: %s", text[:200])
            return self._parse_json(text)
        except Exception as exc:
            log.warning("Ollama /api/chat failed (%s %s): %s", self._base_url, self._model, exc)
            return None

    def _try_generate(self, prompt: str) -> Optional[dict]:
        import logging
        log = logging.getLogger(__name__)
        try:
            payload = json.dumps({
                "model":  self._model,
                "prompt": prompt + '\n\nRespond with only a JSON object, no other text.',
                "stream": False,
            }).encode()
            req = urllib.request.Request(
                f"{self._base_url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read())
            text = data.get("response", "").strip()
            log.debug("Ollama /api/generate raw: %s", text[:200])
            return self._parse_json(text)
        except Exception as exc:
            log.warning("Ollama /api/generate failed (%s %s): %s", self._base_url, self._model, exc)
            return None

    def _parse_json(self, text: str) -> Optional[dict]:
        """Extract and normalise the JSON dict from a model response."""
        if not text:
            return None
        # Try direct parse first (clean JSON output)
        for attempt in (text, text[text.find("{"):text.rfind("}")+1]):
            try:
                result = json.loads(attempt)
                if isinstance(result, dict):
                    return {
                        "phonetic":   str(result.get("phonetic")   or result.get("Phonetic")   or ""),
                        "definition": str(result.get("definition") or result.get("Definition") or ""),
                        "example":    str(result.get("example")    or result.get("Example")    or ""),
                    }
            except (json.JSONDecodeError, ValueError):
                pass
        return None


def get_ai_provider(config) -> AIProvider:
    """Factory — returns the configured provider.
    Accepts both Flask config dicts and plain config objects.
    """
    _get = (lambda k, d=None: config.get(k, d)) if isinstance(config, dict) else (lambda k, d=None: getattr(config, k, d))
    provider = _get("AI_PROVIDER", "claude")
    if provider == "claude":
        api_key = _get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        return ClaudeProvider(api_key=api_key)
    raise ValueError(f"Unknown AI provider: {provider!r}")
