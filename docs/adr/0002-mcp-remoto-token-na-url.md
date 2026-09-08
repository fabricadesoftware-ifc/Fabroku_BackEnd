# ADR 0002: Servidor MCP remoto, somente leitura, com token na URL

## Status

Aceito.

## Contexto

O Fabroku já tinha um servidor MCP: `fabroku mcp` (no `Fabroku_CLI`, Node.js,
`@modelcontextprotocol/sdk`), que sobe localmente via stdio e expõe as mesmas
permissões da CLI — inclusive `fabroku_redeploy` e `fabroku_run_migrate`. Esse
servidor só funciona com clientes MCP capazes de rodar um processo local
(Claude Desktop, Cursor, Codex etc). Ele não ajuda quem usa Claude.ai pelo
navegador ou outro cliente hospedado, porque esses clientes não têm como
executar `fabroku mcp` na máquina do aluno.

Levantamos quais IAs oferecem conector MCP customizado de graça: Claude (web e
Desktop) libera 1 conector custom no plano Free; Le Chat (Mistral) também
libera no free. Nos dois casos o conector é um servidor **remoto** (URL
pública), não um processo local. ChatGPT e Gemini exigem plano pago para MCP
custom, então ficam de fora da via gratuita por enquanto.

A UI de conectores custom do Claude.ai (web) só aceita, hoje, URL do servidor
+ opcionalmente OAuth Client ID/Secret nos "Advanced settings" — não tem campo
para um Bearer token estático (ver
[issue #112](https://github.com/anthropics/claude-ai-mcp/issues/112) do
`claude-ai-mcp`, sem resposta oficial da Anthropic até a data desta ADR).
Implementar OAuth 2.1 completo (authorization server, client registration,
refresh token) só para isso é desproporcional ao escopo — foi cogitado e
descartado.

## Decisão

Adicionamos um segundo servidor MCP, remoto, hospedado pelo próprio backend
Django em `/api/mcp/<token>/`, usando o SDK oficial Python (`mcp`, pacote
`mcp.server.mcpserver.MCPServer`, transporte Streamable HTTP).

Pontos da decisão:

1. **Autenticação via token na própria URL**, não em header. O `<token>` é o
   mesmo `CLIToken` que `fabroku login` já gera (`identity.models.CLIToken`,
   header `Authorization: CLI <token>` em todo o resto da API) — aqui ele só
   viaja na URL em vez de num header, porque URL é a única coisa que a UI web
   do Claude.ai (free) e o Le Chat aceitam configurar sem OAuth. Continua
   funcionando também em clientes que suportam headers (Claude Desktop,
   Cursor), já que a URL sozinha basta.
2. **Somente leitura.** O servidor expõe só `list_apps`, `get_app_status`,
   `get_app_processes` e `get_runtime_logs` — nenhuma tool de
   criar/deploy/parar/apagar. O `fabroku mcp` local já cobre quem precisa de
   permissão de escrita (redeploy, migrate) e roda com o CLI token do próprio
   usuário na própria máquina, um raio de exposição bem menor que um endpoint
   público na internet. Ampliar o remoto pra escrita fica para uma decisão
   futura separada, se for realmente necessário.
3. **Escopado por dono do token.** Toda query filtra por
   `project__users=<usuário do token>` — nunca dá pra ler app de outro aluno,
   mesmo com token válido.
4. **DNS rebinding protection do próprio SDK** (`TransportSecuritySettings`)
   configurada com `settings.BACKEND_URL`, não desligada.
5. **ASGI, montado dentro do `config.asgi.application` existente** (Daphne já
   é o processo `web` do `Procfile`) — sem processo novo no `Procfile`, sem
   porta nova. Foi necessário adicionar o protocolo `lifespan` ao
   `ProtocolTypeRouter`, que antes não existia (Django puro não precisa dele;
   o `session_manager` do MCP, sim).

## Implementação

- `src/mcp_server/tools.py` — `MCPServer` + as 4 tools, reusando ORM direto
  (não os use cases de `applications/use_cases/`, que são para
  criar/deploy/etc., não para leitura simples).
- `src/mcp_server/auth.py` — resolve o token pra um `User` via `CLIToken`.
- `src/mcp_server/asgi.py` — casa `/api/mcp/<token>/...`, injeta o usuário
  resolvido em `scope['state']`, delega pro app Starlette do MCP.
- `src/config/asgi.py` — dispatcher HTTP por path (`/api/mcp/` vai pro MCP, o
  resto pro Django normal) + `lifespan` novo, que dá `run()` ao
  `session_manager` do MCP (sem isso, toda chamada MCP falha com
  `RuntimeError: Task group is not initialized`).
- `tests/integration/test_mcp_server.py` — handshake MCP real (`initialize` →
  `tools/list` → `tools/call`) rodando `config.asgi.application` de ponta a
  ponta, incluindo um teste que confirma que o usuário A não lê app do usuário
  B.

## Consequências

- Alunos com Claude Free ou Le Chat Free ganham acesso de leitura ao Fabroku
  sem instalar nada — só colar a URL com o próprio token.
- O token vai na URL: qualquer coisa que logue URLs completas (proxy, browser
  history se alguém abrir a URL manualmente, referrer header num cenário
  incomum) pode expor o token. Mitigação: o token já é revogável/regenerável
  como qualquer `CLIToken`, e a superfície é só leitura — pior caso é alguém
  ver status/logs de apps do dono do token, não conseguir agir sobre eles.
- `BACKEND_URL` (já existente, usado pra webhooks do GitHub) virou também a
  fonte do `allowed_hosts` da proteção DNS rebinding do MCP — se estiver
  errado em alguma instalação, o endpoint MCP responde 421 pra todo mundo
  mesmo com token válido.

## Alternativas

- **OAuth 2.1 completo no servidor MCP**: mais "correto" pelo spec e teria
  destravado o campo nativo de auth do Claude.ai web, mas é um projeto bem
  maior (authorization server, consent screen, refresh token) — descartado
  por desproporcional ao ganho, considerando que token-na-URL já cobre os
  mesmos clientes.
- **Assistente de chat embutido no dashboard, com IA nossa (backend chamando
  a API da Anthropic)**: cobriria literalmente qualquer navegador, mas exige
  pagar inferência e manter mais um subsistema — descartado a pedido
  explícito do time ("não quero ter que chegar a esse ponto").
- **WebMCP nativo do navegador** (`document.modelContext`, ver commit
  anterior no frontend): mantido como camada adicional, não substituto — só
  funciona em Chrome 149+/Edge 150+ com Origin Trial, cobertura bem menor que
  um servidor MCP remoto que qualquer cliente MCP consegue apontar pra URL.
