"""
Gerenciamento de configuração da CLI (~/.fabroku/config.json).
"""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / '.fabroku'
CONFIG_FILE = CONFIG_DIR / 'config.json'

DEFAULT_CONFIG = {
    'api_url': 'http://localhost:8000',
    'token': None,
    'user': None,
}


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Carrega a configuração. Cria arquivo padrão se não existir."""
    _ensure_dir()
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config: dict):
    """Salva a configuração."""
    _ensure_dir()
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def get_token() -> str | None:
    """Retorna o token salvo ou None."""
    return load_config().get('token')


def get_api_url() -> str:
    """Retorna a URL base da API."""
    return load_config().get('api_url', DEFAULT_CONFIG['api_url'])


def set_credentials(token: str, user: str, api_url: str | None = None):
    """Salva token e usuário após login."""
    config = load_config()
    config['token'] = token
    config['user'] = user
    if api_url:
        config['api_url'] = api_url
    save_config(config)


def clear_credentials():
    """Remove token e usuário (logout)."""
    config = load_config()
    config['token'] = None
    config['user'] = None
    save_config(config)


def is_authenticated() -> bool:
    """Verifica se existe um token salvo."""
    return get_token() is not None
