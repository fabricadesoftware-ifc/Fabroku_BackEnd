# Fabroku

Plataforma open-source, inspirada no Heroku, usando Dokku, para que alunos do Instituto Federal façam deploy gratuito de aplicações do GitHub.

Este README é um tutorial de uso (passo a passo). Para documentação detalhada do código, veja `README-CLI.md` e `README-API.md`.

## Pré-requisitos
- Servidor Dokku acessível (local ou remoto via SSH)
- Python 3.13+ e [PDM](https://pdm.fming.dev/) instalados

## Setup local (API + CLI)
1. Instalar dependências:
   ```bash
   pdm install
   ```
2. Configurar variáveis (opcional):
   ```bash
   export DEBUG=True
   # se for usar Dokku remoto via SSH
   export DOKKU_HOST=dokku@dokku.seudominio.com
   export DOKKU_SSH_OPTS='-i ~/.ssh/id_rsa -p 22'
   ```
3. Rodar migrações e subir a API local (opcional para testes):
   ```bash
   pdm run python src/manage.py migrate
   pdm run python src/manage.py runserver
   # API em http://localhost:8000
   ```
4. Ver ajuda da CLI:
   ```bash
   pdm run fabroku --help
   ```

## Fluxo do usuário (CLI)
1. Criar conta (interativo):
   ```bash
   pdm run fabroku auth register
   ```
2. Fazer login (interativo):
   ```bash
   pdm run fabroku auth login
   ```
3. Criar app no Dokku (com variáveis iniciais):
   ```bash
   pdm run fabroku create-app minha-app \
     --initial-env '{"SECRET_KEY":"s3cr3t","DEBUG":"False"}'
   ```
   Observação: a CLI marca automaticamente a app com uma tag única (`FABROKU_TAG`) do seu usuário. Você só verá/operará suas próprias apps.

4. Definir portas do proxy (exemplo):
   ```bash
   pdm run fabroku ports set minha-app --map http:80:5000
   ```

5. Fazer deploy:
   - Via Git (repositório com app):
     ```bash
     pdm run fabroku deploy minha-app --git-url https://github.com/user/repo#main
     ```
   - Via Smart Deploy (auto-detecção de Dockerfile):
     ```bash
     pdm run fabroku smart-deploy minha-app --git-url https://github.com/user/repo#main --log
     ```
   - Via Imagem Docker:
     ```bash
     pdm run fabroku deploy minha-app --image usuario/repo:tag
     ```

6. Gerenciar serviços (opcional):
   ```bash
   # Postgres
   pdm run fabroku plugin install https://github.com/dokku/dokku-postgres.git --name postgres
   pdm run fabroku postgres create pg1 --option '--image postgres:16'
   pdm run fabroku postgres link pg1 minha-app

   # RabbitMQ
   pdm run fabroku plugin install https://github.com/dokku/dokku-rabbitmq.git --name rabbitmq
   pdm run fabroku rabbitmq create rmq1
   pdm run fabroku rabbitmq link rmq1 minha-app
   ```

7. Listar suas apps:
   ```bash
   pdm run fabroku apps list
   ```

8. Deletar sua app:
   ```bash
   pdm run fabroku delete-app minha-app --force
   ```

## Fluxo via API (opcional)
Endpoints principais (POST salvo quando indicado):
- `POST /api/dokku/apps/create/` body: `{ "app_name": "minha-app", "initial_env": {"KEY":"VAL"} }`
- `POST /api/dokku/deploy/` body: `{ "app_name": "minha-app", "git_url": "https://...#main" }` ou `{ "image": "usuario/repo:tag" }`
- `POST /api/dokku/smart-deploy/` body: `{ "app_name": "minha-app", "git_url": "https://...#main" }`
- `DELETE /api/dokku/apps/<app_name>/?force=true`
- `POST /api/dokku/config/set/` body: `{ "app_name": "minha-app", "env": {"KEY":"VAL"} }`
- `POST /api/dokku/ports/set/` body: `{ "app_name": "minha-app", "mappings": ["http:80:5000"] }`

Documentação:
- Swagger UI: `/api/docs/`
- OpenAPI: `/api/schema/`

## Deploy da API no Dokku
1. Criar app:
   ```bash
   dokku apps:create fabroku-api
   ```
2. Configurar envs essenciais:
   ```bash
   dokku config:set fabroku-api SECRET_KEY=... DEBUG=False
   ```
3. Deploy:
   - via Git: adicione remoto do Dokku e `git push dokku main`
   - ou via container registry: `dokku tags:deploy fabroku-api <image:tag>`

O `Procfile` roda `gunicorn` (web) e executa migrações no `release` automaticamente.

---
- Detalhes técnicos da CLI e API: veja `README-CLI.md` e `README-API.md`.