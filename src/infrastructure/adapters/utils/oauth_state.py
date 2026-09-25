"""Server-tracked, single-use OAuth `state` tokens shared by the web and CLI login
flows and the shared GitHub callback (`git_callback.py`).

Before this existed, `state` was attacker-suppliable (`cli:<port>`) and read back
at face value in the callback: a crafted `port` value (e.g. `1@evil.com`) landed
straight in a redirect URL, and nothing tied the callback to a login this backend
had actually started. Minting the state here — and only trusting a state that
round-trips through `cache` — closes both: the CLI port is validated once, at
mint time, and never re-parsed from client input; and a `state` an attacker makes
up out of thin air matches nothing, so the callback falls back to the safe (web,
no localhost redirect) path instead of guessing.
"""
import secrets

from django.core.cache import cache

OAUTH_STATE_CACHE_PREFIX = 'oauth_state:'
OAUTH_STATE_TTL_SECONDS = 600
CLI_PORT_MIN = 1024
CLI_PORT_MAX = 65535


def validate_cli_port(raw_port: str | None) -> int | None:
    """Parse `raw_port` as a plain ephemeral/registered TCP port number.

    Returns None for anything that isn't a bare base-10 integer in range —
    never interpolate the raw query-param string into a URL.
    """
    if raw_port is None or not raw_port.isdigit():
        return None
    port = int(raw_port)
    if CLI_PORT_MIN <= port <= CLI_PORT_MAX:
        return port
    return None


def generate_oauth_state(*, cli_port: int | None = None) -> str:
    """Mint a single-use state token for one login attempt, optionally bound to an
    already-validated CLI callback port, and remember it server-side."""
    state = secrets.token_urlsafe(24)
    cache.set(f'{OAUTH_STATE_CACHE_PREFIX}{state}', {'cli_port': cli_port}, timeout=OAUTH_STATE_TTL_SECONDS)
    return state


def consume_oauth_state(state: str) -> dict | None:
    """Look up and immediately invalidate a state token (single-use — defends
    against replay). Returns None if it's missing, unknown, or already used."""
    if not state:
        return None
    key = f'{OAUTH_STATE_CACHE_PREFIX}{state}'
    data = cache.get(key)
    cache.delete(key)
    return data
