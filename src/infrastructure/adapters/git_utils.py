import re
from urllib.parse import urlsplit, urlunsplit

GITHUB_REPO_PATH_PARTS = 2
GITHUB_AUTH_URL_PATTERN = re.compile(r'https://[^/\s@]+@github\.com/([^\s]+)')


def parse_github_repo_name(git_url: str | None) -> str | None:
    """Extrai owner/repo de URLs HTTPS, SSH e SSH URL do GitHub."""
    if not git_url:
        return None

    value = git_url.strip()
    parsed = urlsplit(value)
    if parsed.scheme in {'http', 'https'} and parsed.hostname == 'github.com':
        path = parsed.path.strip('/')
        if path.endswith('.git'):
            path = path[:-4]
        parts = path.split('/')
        if len(parts) >= GITHUB_REPO_PATH_PARTS and parts[0] and parts[1]:
            return f'{parts[0]}/{parts[1]}'

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


def build_github_auth_url(git_url: str, token: str) -> str:
    """Monta uma URL HTTPS autenticada para o GitHub sem depender do formato original."""
    repo_name = parse_github_repo_name(git_url)
    if not repo_name or not token:
        return git_url

    return f'https://x-access-token:{token}@github.com/{repo_name}.git'


def mask_git_credentials(git_url: str | None) -> str:
    """Remove credenciais de URLs Git antes de salvar em logs ou mensagens."""
    if not git_url:
        return ''

    masked = GITHUB_AUTH_URL_PATTERN.sub(r'https://***@github.com/\1', git_url)
    if masked != git_url:
        return masked

    parsed = urlsplit(git_url)
    if not parsed.scheme or not parsed.netloc or not (parsed.username or parsed.password):
        return git_url

    host = parsed.hostname or ''
    if parsed.port:
        host = f'{host}:{parsed.port}'

    return urlunsplit((parsed.scheme, f'***@{host}', parsed.path, parsed.query, parsed.fragment))


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

# 23:10 11/06/2026 uma hora antes do dia dos namorados e eu aqui.
# Foi Assim 0:25..
