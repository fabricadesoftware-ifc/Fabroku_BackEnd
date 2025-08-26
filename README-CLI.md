# Fabroku CLI

A Fabroku CLI é uma interface de linha de comando que abstrai operações do Dokku, seguindo a arquitetura hexagonal do projeto (casos de uso -> porta `DokkuService` -> adapter shell/SSH).

## Requisitos
- Python 3.13+
- [PDM](https://pdm.fming.dev/)
- Acesso ao comando `dokku` localmente OU acesso SSH a um host Dokku

## Instalação (dev)
```bash
# Clonar e instalar dependências
pdm install

# Ver ajuda
pdm run fabroku --help
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
- Ao criar um projeto, a CLI injeta automaticamente `FABROKU_TAG=<sua_tag>` na configuração da app Dokku (via `dokku config:set`).
- `project list`, `project destroy`, `project status`, `deploy`, `smart-deploy`, `config set`, `ports set/add/clear` e outros comandos operam somente sobre projetos com `FABROKU_TAG` igual à sua tag.

## Comandos

### auth
```bash
pdm run fabroku auth register
pdm run fabroku auth login
pdm run fabroku auth whoami
pdm run fabroku auth logout
```

### project
Grupo de comandos para gerenciar projetos. O nome do projeto (`<project_name>`) é frequentemente um argumento necessário para os subcomandos.

- Criar projeto (requer login):
  ```bash
  pdm run fabroku project create \
    --name meu-projeto-web \
    --tecnologia Vue \
    --porta 8000 \
    --source-url https://github.com/usuario/meu-app-vue \
    --source-type git \
    --network default \
    --descricao "Meu primeiro projeto Fabroku" \
    --env "VAR1=VAL1" \
    --env "VAR2=VAL2"
  ```
  Campos obrigatórios: `--name`, `--tecnologia`, `--porta`, `--source-url`, `--source-type`, `--network`.

- Listar seus projetos (filtrados por `FABROKU_TAG`):
  ```bash
  # Lista apenas seus projetos
  pdm run fabroku project list

  # Lista todos os projetos (ignora filtro)
  pdm run fabroku project list --all

  # Lista projetos com uma tag específica
  pdm run fabroku project list --tag <tag>
  ```

- Deletar projeto (requer login e confirmação interativa):
  ```bash
  pdm run fabroku project meu-projeto-web destroy
  ```

- Status do projeto:
  ```bash
  pdm run fabroku project meu-projeto-web status
  ```
  Exemplo de saída:
  ```
  NAME           READY    ESTADO       AGE
  meu-projeto-web   0/1      Rascunho     1m
  ```

### deploy
Comando para realizar deploy de uma aplicação. Este comando está em nível superior, mas futuramente pode ser movido para `fabroku project <name> deploy`.

- Deploy via Git:
  ```bash
  pdm run fabroku deploy meu-projeto-web --git-url https://github.com/usuario/meu-app-vue#main
  ```

- Deploy via Imagem:
  ```bash
  pdm run fabroku deploy meu-projeto-web --image usuario/repo:tag
  ```

- Com buildpack explícito (quando aplicável):
  ```bash
  pdm run fabroku deploy meu-projeto-web --git-url https://github.com/usuario/meu-app-vue#main --buildpack https://github.com/heroku/heroku-buildpack-python
  ```

### smart-deploy
Comando para realizar deploy inteligente, analisando o repositório para a melhor estratégia. Este comando está em nível superior, mas futuramente pode ser movido para `fabroku project <name> smart-deploy`.

- Smart Deploy de projeto (analisa repo para melhor estratégia):
  - Se `source-type` for `git`: clona o repositório, detecta `Dockerfile` e executa `dokku git:sync`. 
  - Se `source-type` for `docker_image` e `source-url` for do Docker Hub: realiza `dokku tags:deploy`. 
  - Se `source-type` for `docker_image` e `source-url` for do GitHub (com Dockerfile): procura Dockerfile e executa `dokku git:sync`.
  ```bash
  pdm run fabroku smart-deploy meu-projeto-web \
    --git-url https://github.com/usuario/meu-app-vue#main \
    --log
  ```
  Flags úteis:
  - `--log`: imprime no stderr os passos do smart-deploy (status, analysis, mensagens de erro)

### plugin
Instalação de plugins Dokku. (Comando de nível superior por enquanto)

- Instalar plugin:
```bash
pdm run fabroku plugin install https://github.com/dokku/dokku-postgres.git --name postgres
```

### postgres
Gerenciamento do serviço Postgres. (Comando de nível superior por enquanto)

- Criar serviço:
```bash
pdm run fabroku postgres create pg1 --option '--image postgres:16'
```
- Linkar serviço à um projeto:
```bash
pdm run fabroku postgres link pg1 meu-projeto-web
```

### rabbitmq
Gerenciamento do serviço RabbitMQ. (Comando de nível superior por enquanto)

- Criar serviço:
```bash
pdm run fabroku rabbitmq create rmq1
```
- Linkar serviço à um projeto:
```bash
pdm run fabroku rabbitmq link rmq1 meu-projeto-web
```

### config
Gerenciamento de variáveis de ambiente do projeto. (Comando de nível superior por enquanto)

- Definir variáveis de ambiente:
```bash
pdm run fabroku config set meu-projeto-web --env SECRET_KEY=abc --env DEBUG=False
```

### ports
Configuração de mapeamentos de portas do proxy do Dokku para um projeto. (Comando de nível superior por enquanto)

- Substituir mapeamentos:
```bash
pdm run fabroku ports set meu-projeto-web --map http:80:8000 --map https:443:8000
```
- Adicionar mapeamentos:
```bash
pdm run fabroku ports add meu-projeto-web --map http:8080:8000
```
- Limpar mapeamentos:
```bash
pdm run fabroku ports clear meu-projeto-web
```

## Integração com a API/Web
A CLI opera diretamente via shell/SSH. Para uso via API Web (Django/DRF), utilize os endpoints documentados em `README-API.md`.

## Solução de problemas
- "Você precisa estar autenticado": faça `fabroku auth login` ou `fabroku auth register`.
- "Comando 'dokku' não encontrado": configure `DOKKU_HOST` para SSH remoto ou instale a CLI do Dokku na máquina local.
- "Permissão negada: você não é o owner deste projeto": certifique-se de estar logado e que a app foi criada por você (ver `FABROKU_TAG`).
- Erros de buildpack: defina `--buildpack` no `deploy`/`smart-deploy` quando necessário.
- Dockerfile em subpastas: o `smart-deploy` define `DOKKU_DOCKERFILE_PATH` automaticamente; verifique com `dokku config:get <app> DOKKU_DOCKERFILE_PATH`. 