"""
Cliente HTTP para a API Fabroku.
"""

import requests

from .config import get_api_url, get_token


class APIError(Exception):
    """Erro na chamada à API."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f'[{status_code}] {detail}')


class FabrokuAPI:
    """Cliente para a API REST do Fabroku."""

    def __init__(self):
        self.base_url = get_api_url()
        self.token = get_token()

    @property
    def headers(self) -> dict:
        h = {'Accept': 'application/json'}
        if self.token:
            h['Authorization'] = f'CLI {self.token}'
        return h

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f'{self.base_url}{path}'
        resp = requests.request(method, url, headers=self.headers, timeout=15, **kwargs)
        if resp.status_code >= 400:  # noqa: PLR2004
            try:
                detail = resp.json().get('detail', resp.text)
            except Exception:
                detail = resp.text
            raise APIError(resp.status_code, detail)
        return resp.json()

    def get(self, path: str, **kwargs) -> dict:
        return self._request('GET', path, **kwargs)

    def post(self, path: str, **kwargs) -> dict:
        return self._request('POST', path, **kwargs)

    # --- Endpoints específicos ---

    def check_auth(self) -> dict:
        """Verifica se o token é válido e retorna dados do usuário."""
        return self.get('/api/auth/check/')

    def list_apps(self) -> list:
        """Lista todos os apps do usuário."""
        data = self.get('/api/apps/apps/')
        return data.get('results', [])

    def list_projects(self) -> list:
        """Lista todos os projetos do usuário."""
        data = self.get('/api/projects/projects/')
        return data.get('results', [])

    def get_user_me(self) -> dict:
        """Retorna dados do usuário logado."""
        return self.get('/api/auth/users/me/')
