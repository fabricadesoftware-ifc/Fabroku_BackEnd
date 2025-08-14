# Fabroku API (Django + DRF)

A API do Fabroku expõe endpoints REST para orquestrar operações do Dokku e registrar o estado de deploys. É integrada à arquitetura hexagonal: as views chamam casos de uso (application) que dependem da porta `DokkuService` (domain), implementada via adapter shell/SSH (infrastructure).

- Documentação interativa: `GET /api/docs/` (Swagger UI)
- OpenAPI schema: `GET /api/schema/`

## Autenticação
Os endpoints disponibilizados neste esqueleto não exigem autenticação por padrão. Para um ambiente multiusuário, recomenda-se habilitar JWT (já preparado via SIMPLE_JWT nas settings) e aplicar permissões. O front deve enviar `Authorization: Bearer <token>` ao chamar a API.

No momento, o isolamento por usuário é aplicado principalmente pela CLI por meio da `FABROKU_TAG`. Ao expor endpoints de listagem de deploys, aplique filtros por tag/usuário no backend.

## Endpoints principais
Base path: `/api/`

### Criar app
`POST /api/dokku/apps/create/`
```json
{
  "app_name": "minha-app",
  "initial_env": {
    "SECRET_KEY": "...",
    "DEBUG": "False"
  }
}
```
Resposta 200:
```json
{ "success": true, "message": "Aplicação 'minha-app' criada com sucesso." }
```

### Deploy
`POST /api/dokku/deploy/`
- Via Git:
```json
{ "app_name": "minha-app", "git_url": "https://github.com/user/repo#main", "buildpack": null }
```
- Via Imagem:
```json
{ "app_name": "minha-app", "image": "usuario/repo:tag" }
```
Resposta 200/400:
```json
{ "success": true, "message": "..." }
```

### Smart Deploy (com tracking)
`POST /api/dokku/smart-deploy/`
```json
{ "app_name": "minha-app", "git_url": "https://github.com/user/repo#main", "buildpack": null }
```
Resposta 200/400:
```json
{ "success": true, "message": "...", "deploy_id": 1 }
```
- Registra um `Deploy` com estados: `rascunho` → `em_andamento` → `pronto` (ou `erro`/`abortado`).
- Analisa o repositório em busca de `Dockerfile` e pastas (`docker/`, `deploy/`, `ops/`, `.docker/`); se necessário, define `DOKKU_DOCKERFILE_PATH` antes do deploy.

### Deletar app
`DELETE /api/dokku/apps/<app_name>/?force=true`
Resposta 200/400:
```json
{ "success": true, "message": "..." }
```

### Plugins
`POST /api/dokku/plugins/install/`
```json
{ "plugin_git_url": "https://github.com/dokku/dokku-postgres.git", "name": "postgres" }
```

### Postgres
- `POST /api/dokku/postgres/create/`
```json
{ "service_name": "pg1", "options": ["--image", "postgres:16"] }
```
- `POST /api/dokku/postgres/link/`
```json
{ "service_name": "pg1", "app_name": "minha-app" }
```

### RabbitMQ
- `POST /api/dokku/rabbitmq/create/`
```json
{ "service_name": "rmq1", "options": [] }
```
- `POST /api/dokku/rabbitmq/link/`
```json
{ "service_name": "rmq1", "app_name": "minha-app" }
```

### Config (env)
`POST /api/dokku/config/set/`
```json
{ "app_name": "minha-app", "env": { "SECRET_KEY": "...", "DEBUG": "False" } }
```

### Proxy (ports)
- `POST /api/dokku/ports/set/`
- `POST /api/dokku/ports/add/`
- `POST /api/dokku/ports/clear/`

## Integração com Front-end
- O front deve sugerir autenticação (JWT) e só exibir dados do próprio usuário.
- Ao criar uma app pelo backend, inclua `FABROKU_TAG` se desejar seguir o mesmo modelo de isolamento da CLI.
- Para `smart-deploy`, guarde o `deploy_id` e faça polling em um endpoint de detalhes (a ser adicionado) para ver `status`, `analysis` e `logs`.

Exemplo (React) de chamada:
```ts
async function smartDeploy(appName: string, gitUrl: string) {
  const res = await fetch("/api/dokku/smart-deploy/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ app_name: appName, git_url: gitUrl })
  });
  const data = await res.json();
  if (!res.ok || !data.success) throw new Error(data.message || "Falha no deploy");
  return data.deploy_id as number;
}
``` 