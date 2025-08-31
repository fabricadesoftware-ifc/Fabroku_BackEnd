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

### 1. Criar conta (interativo)
- Não pede matrícula.
  ```bash
  pdm run fabroku auth register
  ```

### 2. Fazer login (interativo)
  ```bash
  pdm run fabroku auth login
  ```

### 3. Criar projeto no Dokku
- Cria um registro de projeto no banco e uma app no Dokku.
- Os campos `nome`, `tecnologia`, `porta`, `url da fonte`, `tipo da fonte` e `rede` são obrigatórios.
- A CLI marca automaticamente o projeto com uma tag única (`FABROKU_TAG`) do seu usuário. Você só verá/operará seus próprios projetos.
  ```bash
  pdm run fabroku project create \
    --name meu-projeto-web \
    --tecnologia Vue \
    --porta 8000 \
    --source-url https://github.com/usuario/meu-app-vue \
    --source-type git \
    --network default \
    --descricao "Meu primeiro projeto Fabroku"
    --env SECRET_KEY=abc --env DEBUG=False
  ```

### 4. Listar seus projetos
  ```bash
  pdm run fabroku project list
  ```

### 5. Obter status do projeto
- Retorna `NAME`, `READY`, `ESTADO` e `AGE`.
  ```bash
  pdm run fabroku project meu-projeto-web status
  ```
  Exemplo de saída:
  ```
  NAME           READY    ESTADO       AGE
  meu-projeto-web   0/1      Rascunho     1m
  ```

### 6. Fazer deploy (smart-deploy)
- Este comando ainda está em nível superior, mas futuramente pode ser movido para `fabroku project <name> deploy`.
  - O `smart-deploy` analisa a URL da fonte e o tipo (`git` ou `docker_image`) para decidir a melhor estratégia. Para deploys baseados nas informações do projeto salvas, use `pdm run fabroku deploy <nome-do-projeto>`.
  - Se `source-type` for `git`: clona o repositório, detecta `Dockerfile` e executa `dokku git:sync`. 
  - Se `source-type` for `docker_image` e `source-url` for do Docker Hub: realiza `dokku tags:deploy`. 
  - Se `source-type` for `docker_image` e `source-url` for do GitHub (com Dockerfile): procura Dockerfile e executa `dokku git:sync`.
  ```bash
  pdm run fabroku smart-deploy meu-projeto-web --git-url https://github.com/usuario/meu-app-vue --log
  ```

### 7. Deletar projeto
- Exige confirmação digitando o nome do projeto.
  ```bash
  pdm run fabroku project meu-projeto-web destroy
  ```

### 8. Gerenciar serviços (ex: Postgres, RabbitMQ)
- Estes comandos ainda estão em nível superior, mas futuramente podem ser movidos para subcomandos de projeto.
  ```bash
  # Postgres
  pdm run fabroku plugin install https://github.com/dokku/dokku-postgres.git --name postgres
  pdm run fabroku postgres create pg1 --option '--image postgres:16'
  pdm run fabroku postgres link pg1 meu-projeto-web

  # RabbitMQ
  pdm run fabroku plugin install https://github.com/dokku/dokku-rabbitmq.git --name rabbitmq
  pdm run fabroku rabbitmq create rmq1
  pdm run fabroku rabbitmq link rmq1 meu-projeto-web
  ```

### 9. Configurar variáveis de ambiente (pode ser usado para o projeto)
  ```bash
  pdm run fabroku config set meu-projeto-web --env CHAVE=VALOR
  ```

### 10. Configurar portas (pode ser usado para o projeto)
  ```bash
  pdm run fabroku ports set meu-projeto-web --map http:80:5000
  ```

## Fluxo via API (opcional)
Endpoints principais:
- `POST /api/project/projects/` (cria projeto)
- `GET /api/project/projects/` (lista projetos)
- `GET /api/project/projects/<nome>/` (detalhes do projeto)
- `PUT /api/project/projects/<nome>/` (atualiza projeto)
- `DELETE /api/project/projects/<nome>/` (deleta projeto)
- `GET /api/project/projects/<nome>/status/` (status do projeto)
- `POST /api/dokku/deploy/` (deploy genérico)
- `POST /api/dokku/smart-deploy/` (smart deploy)

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