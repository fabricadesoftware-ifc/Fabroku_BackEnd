"""
Comando `fabroku login` — Autenticação via GitHub OAuth.

Abre o browser para autenticação e recebe o token via servidor HTTP local.
"""

import socket
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import click

from .config import clear_credentials, get_api_url, is_authenticated, set_credentials


def _find_free_port() -> int:
    """Encontra uma porta livre no sistema."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handler HTTP que recebe o callback OAuth com o token."""

    token: str | None = None
    user: str | None = None
    error: str | None = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == '/callback':
            if 'token' in params:
                _CallbackHandler.token = params['token'][0]
                _CallbackHandler.user = params.get('user', [''])[0]
                self._send_html(
                    '<h1>✅ Login realizado com sucesso!</h1><p>Pode fechar esta janela e voltar para o terminal.</p>',
                    title='Fabroku CLI — Autenticado',
                )
            else:
                error = params.get('error', ['unknown'])[0]
                message = params.get('message', ['Erro na autenticação'])[0]
                _CallbackHandler.error = f'{error}: {message}'
                self._send_html(
                    f'<h1>❌ Erro na autenticação</h1><p>{message}</p>',
                    title='Fabroku CLI — Erro',
                )
        else:
            self._send_html('<p>Aguardando callback...</p>')

    def _send_html(self, body: str, title: str = 'Fabroku CLI'):
        html = f"""<!DOCTYPE html>
<html><head><title>{title}</title>
<style>
  body {{ font-family: system-ui, sans-serif; display: flex; justify-content: center;
         align-items: center; min-height: 100vh; margin: 0; background: #1a1a2e; color: #eee; }}
  div {{ text-align: center; padding: 2rem; }}
</style></head>
<body><div>{body}</div></body></html>"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        """Suprime logs do servidor HTTP."""
        pass


@click.command()
@click.option('--api-url', default=None, help='URL base da API Fabroku (ex: https://api.exemplo.com)')
def login(api_url):
    """Autenticar na plataforma Fabroku via GitHub."""
    if is_authenticated():
        if not click.confirm('Você já está autenticado. Deseja fazer login novamente?'):
            return

    base_url = api_url or get_api_url()

    port = _find_free_port()
    login_url = f'{base_url}/api/auth/cli/login/?port={port}'

    click.echo(f'🔐 Abrindo browser para autenticação...')
    click.echo(f'   URL: {login_url}')
    click.echo(f'   Aguardando callback na porta {port}...\n')

    webbrowser.open(login_url)

    # Servidor local que espera o callback
    _CallbackHandler.token = None
    _CallbackHandler.user = None
    _CallbackHandler.error = None

    server = HTTPServer(('localhost', port), _CallbackHandler)
    server.timeout = 120  # 2 minutos de timeout

    while _CallbackHandler.token is None and _CallbackHandler.error is None:
        server.handle_request()

    server.server_close()

    if _CallbackHandler.error:
        click.echo(f'❌ Erro: {_CallbackHandler.error}')
        raise SystemExit(1)

    # Salva credenciais
    set_credentials(
        token=_CallbackHandler.token,
        user=_CallbackHandler.user or 'unknown',
        api_url=base_url,
    )

    click.echo(f'✅ Autenticado como {click.style(_CallbackHandler.user, fg="green", bold=True)}')
    click.echo(f'   Token salvo em ~/.fabroku/config.json')


@click.command()
def logout():
    """Encerrar a sessão da CLI."""
    if not is_authenticated():
        click.echo('Você não está autenticado.')
        return

    clear_credentials()
    click.echo('👋 Sessão encerrada com sucesso.')
