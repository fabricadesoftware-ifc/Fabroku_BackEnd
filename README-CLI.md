# Fabroku CLI

A Fabroku CLI é uma interface de linha de comando que abstrai operações do Dokku, seguindo a arquitetura hexagonal do projeto (casos de uso -> porta `DokkuService` -> adapter shell/SSH).

- Repositórios Git podem ser implantados diretamente via `dokku git:sync`.
- Imagens Docker podem ser implantadas via `dokku tags:deploy`.
- O comando `smart-deploy` analisa o repositório para detecção de `Dockerfile`/pasta `docker/` e ajusta a configuração automaticamente.

## Requisitos
- Python 3.13+
- [PDM](https://pdm.fming.dev/)
- Acesso ao comando `dokku` localmente OU acesso SSH a um host Dokku

## Instalação (dev)
```bash
# Clonar e instalar dependências
pdm install

# Ver ajuda
dm run fabroku --help
```

## Configuração
- `DOKKU_HOST`: host remoto do Dokku para SSH, por exemplo `dokku@dokku.seudominio.com`.
  - Se usar o usuário `dokku`, não prefixe o subcomando com `dokku` (o adapter já cuida disso).
- `DOKKU_SSH_OPTS`: opções extras para o ssh (ex.: `-i ~/.ssh/id_rsa -p 22`).

Exemplo usando servidor Dokku remoto:
```bash
export DOKKU_HOST=dokku@dokku.exemplo.com
export DOKKU_SSH_OPTS='-i ~/.ssh/id_rsa -p 22'
```

## Autenticação (obrigatória)
A CLI compartilha o mesmo banco do backend via ORM do Django e exige sessão local para operações sensíveis.

- Registrar (modo interativo, sem matrícula):
```bash
pdm run fabroku auth register
```
Perguntas: Nome, Email, Senha (confirmação).

- Login (modo interativo):
```bash
pdm run fabroku auth login
```
Perguntas: Email, Senha.

- Quem sou / Logout:
```bash
pdm run fabroku auth whoami
pdm run fabroku auth logout
```

A sessão é salva em `~/.fabroku/session.json`.

## Ownership e Tag (FABROKU_TAG)
- Cada usuário recebe uma tag única (estável) guardada em `~/.fabroku/users/<email>.json`.
- Ao criar uma app, a CLI injeta automaticamente `FABROKU_TAG=<sua_tag>` na configuração da app (via `dokku config:set`).
- `apps list` e `delete-app` operam somente sobre apps com `FABROKU_TAG` igual à sua tag.

## Comandos

### auth
```bash
pdm run fabroku auth register
pdm run fabroku auth login
pdm run fabroku auth whoami
pdm run fabroku auth logout
```

### apps
Listagem das suas apps (filtradas por `FABROKU_TAG`):
```bash
# Lista apenas suas apps
pdm run fabroku apps list

# Lista todas as apps (ignora filtro)
pdm run fabroku apps list --all

# Lista apps com uma tag específica
pdm run fabroku apps list --tag <tag>
```

### create-app
Cria uma aplicação no Dokku e define variáveis iniciais. Requer login e marca a app com sua `FABROKU_TAG` automaticamente.
```bash
pdm run fabroku create-app minha-app \
  --initial-env '{"SECRET_KEY":"s3cr3t","DEBUG":"False"}'
```

### deploy
Realiza deploy via Git (dokku git:sync) ou via imagem Docker (dokku tags:deploy).
```bash
# Deploy via Git
pdm run fabroku deploy minha-app --git-url https://github.com/user/repo#main

# Deploy via Imagem
pdm run fabroku deploy minha-app --image usuario/repo:tag

# Com buildpack explícito (quando aplicável)
pdm run fabroku deploy minha-app --git-url https://github.com/user/repo#main --buildpack https://github.com/heroku/heroku-buildpack-python
```

### smart-deploy
Fluxo que analisa o repositório e decide a melhor estratégia:
- Clona de forma rasa (`--depth 1`) a branch indicada (padrão `main` ou a especificada em `<url>#<branch>`)
- Detecta `Dockerfile` na raiz ou em pastas comuns (`docker/`, `deploy/`, `ops/`, `.docker/`)
- Se o `Dockerfile` não estiver na raiz, define `DOKKU_DOCKERFILE_PATH` automaticamente
- Executa `dokku git:sync`

```bash
pdm run fabroku smart-deploy minha-app \
  --git-url https://github.com/user/repo#main \
  --log
```

### delete-app
Remove uma aplicação do Dokku. Requer login e ownership (verificação por `FABROKU_TAG`).
```bash
pdm run fabroku delete-app minha-app --force
```

### plugin install
Instala um plugin Dokku via repositório Git.
```bash
pdm run fabroku plugin install https://github.com/dokku/dokku-postgres.git --name postgres
```

### postgres
Gerencia serviço Postgres.
```bash
# Criar serviço
pdm run fabroku postgres create pg1 --option '--image postgres:16'

# Linkar à app
pdm run fabroku postgres link pg1 minha-app
```

### rabbitmq
Gerencia serviço RabbitMQ.
```bash
# Criar serviço
pdm run fabroku rabbitmq create rmq1

# Linkar à app
pdm run fabroku rabbitmq link rmq1 minha-app
```

### config set
Define variáveis de ambiente na app.
```bash
pdm run fabroku config set minha-app --env SECRET_KEY=abc --env DEBUG=False
```

### ports (proxy)
Configura mapeamentos de portas do proxy do Dokku.
```bash
# Substitui os mapeamentos
pdm run fabroku ports set minha-app --map http:80:5000 --map https:443:5000

# Adiciona mapeamentos
pdm run fabroku ports add minha-app --map http:8080:5000

# Limpa mapeamentos
pdm run fabroku ports clear minha-app
```

## Integração com a API/Web
A CLI opera diretamente via shell/SSH. Para uso via API Web (Django/DRF), utilize os endpoints documentados em `README-API.md`.

## Solução de problemas
- "Você precisa estar autenticado": faça `fabroku auth login` ou `fabroku auth register`.
- "Comando 'dokku' não encontrado": configure `DOKKU_HOST` para SSH remoto ou instale a CLI do Dokku na máquina local.
- Erros de buildpack: defina `--buildpack` no `deploy`/`smart-deploy` quando necessário.
- Dockerfile em subpastas: o `smart-deploy` define `DOKKU_DOCKERFILE_PATH` automaticamente; verifique com `dokku config:get <app> DOKKU_DOCKERFILE_PATH`. 