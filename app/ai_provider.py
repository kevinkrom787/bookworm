"""
AI provider abstraction.

Add on-device providers here later — swap by setting config.AI_PROVIDER.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


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
        )
        return msg.content[0].text.strip()


def get_ai_provider(config) -> AIProvider:
    """Factory — returns the configured provider."""
    provider = getattr(config, "AI_PROVIDER", "claude")
    if provider == "claude":
        api_key = getattr(config, "ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        return ClaudeProvider(api_key=api_key)
    raise ValueError(f"Unknown AI provider: {provider!r}")
