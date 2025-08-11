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

## Mapeamento para Dokku (exemplos)

- create-app → `dokku apps:create <app>` e `dokku config:set` (se `--initial-env`)
- deploy → `dokku tags:deploy` (imagem) ou `dokku git:sync` (git)
- delete-app → `dokku apps:destroy <app> [--force]`
- plugin install → `dokku plugin:install <git_url> [name]`
- postgres create → `dokku postgres:create <service> [options...]`
- postgres link → `dokku postgres:link <service> <app>`
- rabbitmq create → `dokku rabbitmq:create <service> [options...]`
- rabbitmq link → `dokku rabbitmq:link <service> <app>`
- config set → `dokku config:set <app> KEY=VALUE ...`
- ports set → `dokku proxy:ports-set <app> ...`
- ports add → `dokku proxy:ports-add <app> ...`
- ports clear → `dokku proxy:ports-clear <app>`

## Variáveis de Ambiente (SSH)
- `DOKKU_HOST`: `dokku@host` (ou outro usuário se necessário)
- `DOKKU_SSH_OPTS`: por exemplo `-p 1022 -i C:\Users\User\.ssh\id_ed25519 -o StrictHostKeyChecking=accept-new`