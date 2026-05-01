"""
PostHog analytics wrapper. All calls are no-ops when POSTHOG_API_KEY is unset.
Uses the Posthog client class (v3 API) with atexit flush so events aren't
dropped when Fly.io auto-stops the machine.
"""
import atexit
from posthog import Posthog as _Client

_client: _Client | None = None


def init(api_key: str, host: str) -> None:
    global _client
    if not api_key:
        return
    _client = _Client(api_key, host=host)
    atexit.register(_client.shutdown)


def capture(distinct_id: str, event: str, props: dict | None = None) -> None:
    if _client is None:
        return
    _client.capture(str(distinct_id), event, properties=props or {})


def identify(distinct_id: str, props: dict | None = None) -> None:
    if _client is None:
        return
    _client.identify(str(distinct_id), properties=props or {})
