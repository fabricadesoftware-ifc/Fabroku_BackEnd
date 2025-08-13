# Fabroku

Fabroku é uma CLI em Python (Click) que cria uma camada de abstração sobre o Dokku, seguindo arquitetura hexagonal (Ports and Adapters). Pode ser usada de forma independente ou integrada com a API Django deste projeto.

## Como instalar em modo desenvolvimento

1. Requer PDM e Python 3.13+
2. Instale as dependências: `pdm install`
3. Rode a CLI: `pdm run fabroku --help`

## Uso

```
fabroku --help
fabroku create-app <app_name> [--initial-env '{"KEY":"VALUE"}']
fabroku deploy <app_name> [--git-url <url>#<branch>] [--image user/repo:tag] [--buildpack <url>]
fabroku delete-app <app_name> [--force]
fabroku plugin install <plugin_git_url> [--name <name>]
fabroku postgres create <service_name> [--option <opt> ...]
fabroku postgres link <service_name> <app_name>
fabroku rabbitmq create <service_name> [--option <opt> ...]
fabroku rabbitmq link <service_name> <app_name>
fabroku config set <app_name> --env KEY=VALUE [--env KEY2=VALUE2 ...]
fabroku ports set <app_name> --map http:80:5000 [--map https:443:5000 ...]
fabroku ports add <app_name> --map http:8080:5000
fabroku ports clear <app_name>
```

Observação: Para usar Dokku remoto via SSH, defina `DOKKU_HOST` (ex.: `user@dokku-host`) e opcionalmente `DOKKU_SSH_OPTS`.

## API Web (Django + DRF)

Endpoints principais (POST salvo quando indicado):
- `POST /api/dokku/apps/create/` body: `{ "app_name": "minha-app", "initial_env": {"KEY":"VAL"} }`
- `POST /api/dokku/deploy/` body: `{ "app_name": "minha-app", "git_url": "https://...#main" }` ou `{ "image": "usuario/repo:tag" }`
- `DELETE /api/dokku/apps/<app_name>/` query: `?force=true`
- `POST /api/dokku/plugins/install/` body: `{ "plugin_git_url": "https://...", "name": "opcional" }`
- `POST /api/dokku/postgres/create/` body: `{ "service_name": "pg1", "options": ["--some", "--opts"] }`
- `POST /api/dokku/postgres/link/` body: `{ "service_name": "pg1", "app_name": "minha-app" }`
- `POST /api/dokku/rabbitmq/create/` body: `{ "service_name": "rmq1", "options": [] }`
- `POST /api/dokku/rabbitmq/link/` body: `{ "service_name": "rmq1", "app_name": "minha-app" }`
- `POST /api/dokku/config/set/` body: `{ "app_name": "minha-app", "env": {"KEY":"VAL"} }`
- `POST /api/dokku/ports/set/` body: `{ "app_name": "minha-app", "mappings": ["http:80:5000"] }`
- `POST /api/dokku/ports/add/` body: `{ "app_name": "minha-app", "mappings": ["http:8080:5000"] }`
- `POST /api/dokku/ports/clear/` body: `{ "app_name": "minha-app" }`

Documentação e schema:
- OpenAPI: `/api/schema/`
- Swagger UI: `/api/docs/`

## Deploy no Dokku

Pré-requisitos no servidor Dokku:
- Plugins conforme necessidade (postgres, rabbitmq etc.)
- Variáveis de ambiente (SECRET_KEY, DATABASE_URL, etc.)

Passos:
1. Crie a app: `dokku apps:create fabroku-api`
2. Configure envs essenciais:
   - `dokku config:set fabroku-api SECRET_KEY=...`
   - `dokku config:set fabroku-api DEBUG=False`
3. Deploy:
   - Via Git: adicione o remoto do dokku e `git push dokku Feat-cli:main` (ou a branch que preferir)
   - Ou use container registry com `dokku tags:deploy`
4. Migrations são executadas automaticamente via `release` no Procfile.

Procfile:
```
web: gunicorn django_project.wsgi --chdir src --bind 0.0.0.0:$PORT
release: python src/manage.py migrate --noinput
```

## Arquitetura

```
src/fabroku/
  domain/            # Regras e contratos (ports)
  application/       # Casos de uso
  infrastructure/    # Adapters concretos (shell, django, http)
  cli/               # Interface via Click
```

Para adicionar um novo comando:
1. Crie um novo caso de uso em `application/use_cases/` que use apenas as ports do domínio.
2. Se necessário, adicione capacidades às ports em `domain/ports.py`.
3. Implemente/expanda um adapter em `infrastructure/adapters/` que satisfaça a port.
4. Adicione um subcomando Click em `cli/cli.py` chamando o caso de uso.