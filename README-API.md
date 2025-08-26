# Fabroku API (Django + DRF)

A API do Fabroku expõe endpoints REST para orquestrar operações do Dokku e registrar o estado de deploys. É integrada à arquitetura hexagonal: as views chamam casos de uso (application) que dependem da porta `DokkuService` (domain), implementada via adapter shell/SSH (infrastructure).

- Documentação interativa: `GET /api/docs/` (Swagger UI)
- OpenAPI schema: `GET /api/schema/`

## Autenticação
Os endpoints de gerenciamento de projetos (`/api/project/projects/`) exigem autenticação. Os endpoints Dokku (`/api/dokku/`) também precisam de autenticação para operações como deploy ou configuração de serviços.

Recomenda-se habilitar JWT (já preparado via SIMPLE_JWT nas settings) e aplicar permissões. O front deve enviar `Authorization: Bearer <token>` ao chamar a API.

O isolamento por usuário é aplicado pelos casos de uso que verificam a `FABROKU_TAG` nas variáveis de ambiente dos projetos e o `request.user` autenticado.

## Endpoints

### Gerenciamento de Projetos (`/api/project/`) 

Estes endpoints lidam com a gestão dos registros de projetos no banco de dados e as operações correspondentes no Dokku. 

- **Listar/Criar Projetos**
  - `GET /api/project/projects/`
    - Retorna a lista de projetos do usuário autenticado.
  - `POST /api/project/projects/`
    - Cria um novo registro de projeto no banco e provisiona a app no Dokku.
    - **Requisição (body JSON):**
      ```json
      {
        "nome": "meu-projeto-web",
        "descricao": "Meu primeiro projeto Fabroku",
        "tecnologia": "Vue",
        "source_type": "git",
        "source_url": "https://github.com/usuario/meu-app-vue",
        "network": 1, // ID da network
        "porta": 8000,
        "variaveis_ambiente": {"VAR1":"VAL1", "VAR2":"VAL2"}
      }
      ```
    - **Campos obrigatórios:** `nome`, `tecnologia`, `porta`, `source_type`, `source_url`, `network` (ID da rede existente).
    - O `usuario` é automaticamente associado ao `request.user` autenticado.
    - O `status` inicial é definido como `"rascunho"`.
    - Uma `FABROKU_TAG` única do usuário é injetada automaticamente nas `variaveis_ambiente` da app Dokku.
    - **Resposta 201 (Sucesso):**
      ```json
      { "id": 1, "nome": "meu-projeto-web", ... }
      ```
    - **Resposta 400 (Erro):**
      ```json
      { "detail": "Mensagem de erro..." }
      ```

- **Detalhes/Atualizar/Deletar Projeto**
  - `GET /api/project/projects/<str:nome>/`
  - `PUT /api/project/projects/<str:nome>/`
  - `PATCH /api/project/projects/<str:nome>/`
  - `DELETE /api/project/projects/<str:nome>/`
    - O `DELETE` acionará a destruição da app no Dokku e do registro no banco.
    - **Requisição DELETE (sem body):**
      ```
      DELETE /api/project/projects/meu-projeto-web/
      ```
    - **Resposta 204 (Sucesso DELETE):** (sem conteúdo)
    - **Resposta 400 (Erro):**
      ```json
      { "detail": "Mensagem de erro..." }
      ```

- **Status do Projeto**
  - `GET /api/project/projects/<str:project_name>/status/`
  - **Resposta 200:**
    ```json
    {
      "name": "meu-projeto-web",
      "ready": "0/1",
      "estado": "Rascunho",
      "age": "1m"
    }
    ```

### Gerenciamento de Redes (`/api/project/`) 

Estes endpoints gerenciam as redes Docker que podem ser vinculadas aos projetos. 

- **Listar/Criar Redes**
  - `GET /api/project/networks/`
  - `POST /api/project/networks/`
    - **Requisição (body JSON):**
      ```json
      { "name": "minha-rede", "description": "Rede isolada para ambiente de testes" }
      ```
    - **Resposta 201 (Sucesso):**
      ```json
      { "id": 1, "name": "minha-rede", "description": "..." }
      ```

- **Detalhes/Atualizar/Deletar Rede**
  - `GET /api/project/networks/<str:name>/`
  - `PUT /api/project/networks/<str:name>/`
  - `PATCH /api/project/networks/<str:name>/`
  - `DELETE /api/project/networks/<str:name>/`

### Operações Dokku Diretas (`/api/dokku/`) 

Estes endpoints realizam operações Dokku que não estão diretamente ligadas ao ciclo de vida de um `Projeto` do Fabroku ou podem ser usadas em cenários mais avançados. 

- **Deploy Genérico**
  - `POST /api/dokku/deploy/`
  - **Requisição (body JSON):**
    - Via Git:
      ```json
      { "app_name": "meu-app-dokku", "git_url": "https://github.com/usuario/repo.git#main", "buildpack": null }
      ```
    - Via Imagem:
      ```json
      { "app_name": "meu-app-dokku", "image": "usuario/repo:tag" }
      ```
  - **Resposta 200/400:**
    ```json
    { "success": true, "message": "..." }
    ```

- **Smart Deploy**
  - `POST /api/dokku/smart-deploy/`
  - **Requisição (body JSON):**
    ```json
    { "app_name": "meu-app-dokku", "source_type": "git", "source_url": "https://github.com/usuario/repo.git#main", "buildpack": null }
    ```
    ou para imagem docker:
    ```json
    { "app_name": "meu-app-dokku", "source_type": "docker_image", "source_url": "usuario/repo:tag" }
    ```
  - **Resposta 200/400:**
    ```json
    { "success": true, "message": "...", "deploy_id": 1 }
    ```
  - Registra um `Deploy` com estados: `rascunho` → `em_andamento` → `pronto` (ou `erro`/`abortado`).
  - Analisa a fonte (Git ou Docker Image) e realiza o deploy apropriado.

- **Deletar App Dokku**
  - `DELETE /api/dokku/apps/<str:app_name>/`
  - **Requisição (sem body, pode ter `?force=true` na URL):**
    ```
    DELETE /api/dokku/apps/meu-app-dokku/
    ```

- **Outros serviços Dokku (Exemplos)**
  - `POST /api/dokku/plugins/install/`
    ```json
    { "plugin_git_url": "https://github.com/dokku/dokku-postgres.git", "name": "postgres" }
    ```
  - `POST /api/dokku/postgres/create/`
    ```json
    { "service_name": "pg1", "options": ["--image", "postgres:16"] }
    ```
  - `POST /api/dokku/postgres/link/`
    ```json
    { "service_name": "pg1", "app_name": "meu-app-dokku" }
    ```
  - `POST /api/dokku/config/set/`
    ```json
    { "app_name": "meu-app-dokku", "env": { "SECRET_KEY": "..." } }
    ```
  - `POST /api/dokku/ports/set/`
    ```json
    { "app_name": "meu-app-dokku", "mappings": ["http:80:8000"] }
    ```

## Integração com Front-end
- O front deve sugerir autenticação (JWT) e só exibir dados do próprio usuário.
- Ao criar um projeto pelo backend, garanta que o usuário autenticado esteja associado ao `Projeto` no momento da criação.
- Para `smart-deploy`, guarde o `deploy_id` e faça polling em um endpoint de detalhes (a ser adicionado) para ver `status`, `analysis` e `logs`.

---

## Deploy da API no Dokku
1. Crie o aplicativo Dokku:
   ```bash
   dokku apps:create fabroku-api
   ```
2. Configure variáveis de ambiente essenciais (SECRET_KEY, DEBUG, DATABASE_URL):
   ```bash
   dokku config:set fabroku-api SECRET_KEY=... DEBUG=False DATABASE_URL=postgres://user:password@host:port/database
   ```
3. Realize o deploy (via Git ou imagem Docker):
   - Via Git: adicione o remote do Dokku e `git push dokku main`.
   - Via container registry: `dokku tags:deploy fabroku-api <image:tag>`.

O `Procfile` configurado no projeto executa `gunicorn` (para servir a web API) e executa migrações (`python src/manage.py migrate`) durante a fase de `release` (automaticamente pelo Dokku). 