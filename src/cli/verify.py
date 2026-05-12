"""
Comando `fabroku verify` — Verifica arquivos necessários para deploy.

Lógica baseada no diagrama:
  - É da fábrica?
    - NÃO → verifica "Tipo aplicação": Frontend ou Backend
    - SIM → "Tipo aplicação" OU "Personalizado" (pula verificação)

  Frontend precisa de: .buildpacks, .static, static.json
  Backend precisa de:  Procfile, requirements.txt, runtime.txt
"""

from pathlib import Path

import click

from .config import get_token, is_authenticated

# Arquivos necessários por tipo
REQUIRED_FILES = {
    'frontend': {
        'files': ['.buildpacks', '.static', 'static.json'],
        'label': 'FrontEnd',
        'description': 'Aplicação SPA/estática (Vue, React, etc.)',
    },
    'backend': {
        'files': ['Procfile', 'requirements.txt', 'runtime.txt'],
        'label': 'BackEnd',
        'description': 'Aplicação Python (Django, Flask, etc.)',
    },
}

# Conteúdo padrão para arquivos que faltam
DEFAULT_CONTENTS = {
    '.buildpacks': 'https://github.com/heroku/heroku-buildpack-nodejs\nhttps://github.com/heroku/heroku-buildpack-static\n',
    '.static': '',
    'static.json': '{\n  "root": "dist",\n  "clean_urls": true,\n  "routes": {\n    "/**": "index.html"\n  },\n  "https_only": true\n}\n',
    'Procfile': 'web: gunicorn config.wsgi --bind 0.0.0.0:$PORT\n',
    'requirements.txt': '# Gerado por fabroku verify\n# Adicione suas dependências aqui\n',
    '.python-version': 'python-3.13.2\n',
}


def _detect_app_type(directory: Path) -> str | None:
    """Tenta detectar automaticamente o tipo de app."""
    # Se tem package.json → frontend
    if (directory / 'package.json').exists():
        return 'frontend'
    # Se tem manage.py ou setup.py ou pyproject.toml com python → backend
    if (directory / 'manage.py').exists() or (directory / 'requirements.txt').exists():
        return 'backend'
    if (directory / 'pyproject.toml').exists():
        return 'backend'
    return None


def _check_files(directory: Path, app_type: str) -> tuple[list[str], list[str]]:
    """
    Verifica arquivos necessários.
    Retorna (presentes, faltando).
    """
    config = REQUIRED_FILES[app_type]
    present = []
    missing = []

    for filename in config['files']:
        if (directory / filename).exists():
            present.append(filename)
        else:
            missing.append(filename)

    return present, missing


@click.command()
@click.option(
    '--type',
    '-t',
    'app_type',
    type=click.Choice(['frontend', 'backend'], case_sensitive=False),
    default=None,
    help='Tipo da aplicação (frontend ou backend). Auto-detectado se omitido.',
)
@click.option(
    '--dir',
    '-d',
    'directory',
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    default='.',
    help='Diretório do projeto (padrão: diretório atual).',
)
@click.option('--fix', is_flag=True, help='Gerar automaticamente os arquivos faltantes com conteúdo padrão.')
def verify(app_type, directory, fix):
    """Verificar se o projeto tem os arquivos necessários para deploy."""
    dir_path = Path(directory)

    click.echo(f'📂 Verificando: {click.style(str(dir_path), bold=True)}')
    click.echo()

    # Detecta tipo se não informado
    if app_type is None:
        detected = _detect_app_type(dir_path)
        if detected:
            app_type = detected
            click.echo(f'🔍 Tipo detectado: {click.style(REQUIRED_FILES[detected]["label"], fg="cyan", bold=True)}')
        else:
            click.echo('⚠️  Não foi possível detectar o tipo da aplicação.')
            click.echo('   Use --type frontend ou --type backend')
            raise SystemExit(1)
    else:
        app_type = app_type.lower()

    config = REQUIRED_FILES[app_type]
    click.echo(f'   Tipo: {config["label"]} — {config["description"]}')
    click.echo()

    # Verifica se o usuário é da fábrica (se autenticado)
    is_fabric = False
    if is_authenticated():
        try:
            from .api import FabrokuAPI

            api = FabrokuAPI()
            user_data = api.get_user_me()
            is_fabric = user_data.get('is_fabric', False) or user_data.get('is_superuser', False)
            if is_fabric:
                click.echo(f'🏭 Usuário da Fábrica — configuração personalizada disponível')
                click.echo()
        except Exception:
            pass  # Continua sem verificação de fábrica

    # Verifica arquivos
    present, missing = _check_files(dir_path, app_type)

    # Mostra resultado
    for filename in present:
        click.echo(f'  ✅ {click.style(filename, fg="green")}')

    for filename in missing:
        click.echo(f'  ❌ {click.style(filename, fg="red")} — faltando')

    click.echo()

    if not missing:
        click.echo(click.style('🚀 Projeto pronto para deploy!', fg='green', bold=True))
        return

    # Tem arquivos faltando
    click.echo(click.style(f'⚠️  {len(missing)} arquivo(s) faltando para deploy.', fg='yellow', bold=True))

    if is_fabric:
        click.echo('   (Membros da Fábrica podem usar configuração personalizada)')

    if fix:
        click.echo()
        _generate_missing_files(dir_path, missing)
    else:
        click.echo(f'   Use {click.style("fabroku verify --fix", bold=True)} para gerar automaticamente.')


def _generate_missing_files(directory: Path, missing: list[str]):
    """Gera arquivos faltantes com conteúdo padrão."""
    for filename in missing:
        filepath = directory / filename
        content = DEFAULT_CONTENTS.get(filename, '')
        filepath.write_text(content, encoding='utf-8')
        click.echo(f'  📝 Criado: {click.style(filename, fg="cyan")}')

    click.echo()
    click.echo(click.style('✅ Arquivos gerados! Revise o conteúdo antes do deploy.', fg='green'))
