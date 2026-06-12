import re
from urllib.parse import urlsplit, urlunsplit


def parse_github_repo_name(git_url: str | None) -> str | None:
    """Extrai owner/repo de URLs HTTPS, SSH e SSH URL do GitHub."""
    if not git_url:
        return None

    value = git_url.strip()
    patterns = (
        r'https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$',
        r'git@github\.com:([^/]+/[^/]+?)(?:\.git)?$',
        r'ssh://git@github\.com/([^/]+/[^/]+?)(?:\.git)?/?$',
    )

    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            return match.group(1)

    return None


def parse_github_branch_from_ref(ref: str | None) -> str | None:
    """Converte refs/heads/minha/branch para minha/branch sem quebrar barras."""
    if not ref:
        return None

    if ref.startswith('refs/heads/'):
        return ref.removeprefix('refs/heads/')

    if ref.startswith('refs/tags/'):
        return None

    return ref


def normalize_webhook_url(url: str | None) -> str:
    """Normaliza URL para comparar webhooks sem depender de barra final."""
    if not url:
        return ''

    value = url.strip()
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return value.rstrip('/')

    path = parts.path.rstrip('/')
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ''))


def get_github_hook_events(hook) -> list[str]:
    events = getattr(hook, 'events', None)
    if events is None:
        events = getattr(hook, 'raw_data', {}).get('events', [])
    return list(events or [])

#23:10 11/06/2026 uma hora antes do dia dos namorados e eu aqui.
# Foi Assim 0:25..
