"""
Thin wrapper around the PostHog Python SDK.
All calls are no-ops when POSTHOG_API_KEY is not set.
"""
import posthog as _ph

_ready = False


def init(api_key: str, host: str) -> None:
    global _ready
    if not api_key:
        return
    _ph.api_key  = api_key
    _ph.host     = host
    _ph.disabled = False
    _ready = True


def capture(distinct_id: str, event: str, props: dict | None = None) -> None:
    if not _ready:
        return
    _ph.capture(distinct_id, event, properties=props or {})


def identify(distinct_id: str, props: dict | None = None) -> None:
    if not _ready:
        return
    _ph.identify(distinct_id, properties=props or {})
