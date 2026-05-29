# Fabroku Backend

## Como subir uma instalacao do Fabroku

Para uma instalacao nova funcionar de ponta a ponta, o Fabroku precisa de
quatro blocos configurados: banco interno, broker do Celery, OAuth do GitHub e
acesso SSH ao servidor Dokku. A chave SSH e o usuario do servidor sao
necessarios, mas nao sao a unica parte da configuracao.

### 1. Preparar o servidor Dokku

No servidor que vai hospedar os apps dos usuarios:

- Instale e configure o Dokku.
- Instale os plugins de servico que a instalacao vai oferecer, por exemplo
  Postgres e Redis.
- Garanta que o usuario SSH configurado no Fabroku consiga executar comandos
  Dokku sem senha interativa.
- Cadastre a chave publica correspondente a `DOKKU_SSH_KEY` no servidor.
- Confirme host, porta e usuario SSH que o backend vai usar.

Variaveis principais:

```env
DOKKU_SSH_KEY=/app/keys/dokku_id_rsa
DOKKU_SSH_USERNAME=dokku
DOKKU_SSH_HOST=dokku.example.com
DOKKU_SSH_PORT=22
```

Em algumas instalacoes o usuario pode nao ser `dokku`, desde que ele consiga
executar os comandos Dokku necessarios. O importante e o backend conseguir
criar apps, configurar variaveis, rodar deploys, escalar processos e gerenciar
servicos pelo Dokku.

### 2. Configurar o backend do Fabroku

O backend precisa de um banco para guardar usuarios, projetos, apps, logs,
auditoria e resultados das tarefas. Tambem precisa de um broker para o Celery.

Variaveis obrigatorias/recomendadas:

```env
SECRET_KEY=troque-este-valor
DEBUG=False
ALLOWED_HOSTS=fabroku-api.example.com
DATABASE_URL=postgres://usuario:senha@host:5432/fabroku
BROKER_URL=amqp://usuario:senha@host:5672/vhost

FRONTEND_URL=https://fabroku.example.com
BACKEND_URL=https://fabroku-api.example.com

GITHUB_CLIENT_ID=seu-client-id
GITHUB_CLIENT_SECRET=seu-client-secret
GITHUB_REDIRECT_URI=https://fabroku-api.example.com/api/auth/github/callback
GITHUB_WEBHOOK_SECRET=um-segredo-para-webhooks
```

Se usar cookies entre subdominios, configure tambem:

```env
AUTH_COOKIE_DOMAIN=.example.com
CORS_ALLOWED_ORIGINS=https://fabroku.example.com
CSRF_TRUSTED_ORIGINS=https://fabroku.example.com
```

Depois de configurar as variaveis, rode as migrations e mantenha web e worker
ativos:

```bash
python src/manage.py migrate
dokku ps:scale fabroku-api web=1 worker=1
```

O `Procfile` do backend ja possui:

- `release`: roda migrations durante o deploy.
- `web`: sobe a API Django/Gunicorn.
- `worker`: processa tarefas longas do Celery, como deploys e comandos Dokku.
- `flower`: opcional para monitoramento do Celery.

### 3. Configurar o GitHub OAuth

Crie um OAuth App no GitHub e configure:

- Homepage URL: URL publica do frontend.
- Authorization callback URL:
  `https://fabroku-api.example.com/api/auth/github/callback`.

O `GITHUB_CLIENT_ID` e o `GITHUB_CLIENT_SECRET` desse app devem ir para o
backend. Se o callback estiver errado, login web e login da CLI vao falhar.

### 4. Configurar o frontend

O frontend precisa apontar para a API publica:

```env
VITE_API_BASE_URL=https://fabroku-api.example.com/api
```

Para apps frontend hospedados pelo Dokku/Nginx, normalmente tambem sao usadas:

```env
NGINX_ROOT=dist
NGINX_DEFAULT_REQUEST=index.html
```

### 5. Politica de acesso da instalacao

Por padrao, o Fabroku preserva a regra da instalacao IFC. Para outra
organizacao, ajuste a politica de login:

```env
AUTH_ALLOWED_EMAIL_DOMAINS=example.com
AUTH_ALLOW_ALL_VERIFIED_EMAILS=False
AUTH_EMAIL_REJECTION_MESSAGE=Seu email nao esta autorizado nesta instalacao.
```

Se quiser permitir qualquer conta GitHub com email verificado:

```env
AUTH_ALLOWED_EMAIL_DOMAINS=
AUTH_ALLOW_ALL_VERIFIED_EMAILS=True
```

### Checklist rapido

- Backend responde em `https://fabroku-api.example.com/api/`.
- Frontend abre e consegue chamar `/api/platform/config/`.
- GitHub OAuth redireciona para `/callback` no frontend apos login.
- Celery worker esta rodando.
- Backend consegue conectar por SSH no Dokku.
- `BACKEND_URL` e publico, para webhooks do GitHub funcionarem.
- Cookies, CORS e CSRF apontam para os dominios publicos corretos.

## Configuracao por instalacao

O Fabroku preserva os defaults da instalacao IFC, mas pode ser executado em
outros ambientes usando variaveis de ambiente:

- `AUTH_ALLOWED_EMAIL_DOMAINS`: dominios de email GitHub verificados que podem entrar. Default: `estudantes.ifc.edu.br`.
- `AUTH_ALLOW_ALL_VERIFIED_EMAILS`: quando `True`, qualquer email verificado do GitHub pode entrar.
- `AUTH_EMAIL_REJECTION_MESSAGE`: mensagem exibida quando o email nao passa na politica de acesso.
- `FABROKU_ORGANIZATION_NAME`: nome da organizacao exibido no frontend. Default: `Fábrica de Software`.
- `FABROKU_PRIVILEGED_ROLE_LABEL`: label publico para usuarios com `is_fabric=True`.
- `FABROKU_REGULAR_ROLE_LABEL`: label publico para usuarios comuns.
- `FABROKU_APP_DOMAIN_SUFFIX`: sufixo mostrado na criacao de apps.
- `CSRF_TRUSTED_ORIGIN_REGEXES`, `CORS_ALLOWED_ORIGIN_REGEXES` e `AUTH_COOKIE_DOMAIN`: ajustam dominios publicos da instalacao.
- `SERVICE_PROXY_POSTGRES_HOST`, `SERVICE_PROXY_POSTGRES_PORT`, `SERVICE_PROXY_REDIS_HOST`, `SERVICE_PROXY_REDIS_PORT`, `SERVICE_PROXY_RABBITMQ_HOST` e `SERVICE_PROXY_RABBITMQ_PORT`: hosts e portas dos proxies de servicos, quando usados.
