---
flow: app-concurrent-actions
commit: backend 6148b46 · frontend 4cc5fa6
status: implementado (2026-10-28)
---

# Decisões: ações concorrentes sobre um App

Marque cada achado com **aprovar**, **reprovar** ou **ajustar** (e comente). Só os aprovados viram implementação. Os cenários C1–C14 estão na matriz de `flow.md`.

## A-01 · Comandos e escala sequestram o `task_id` de uma operação em andamento · severidade: alta

- **Cenários:** C6, C7, C9
- **Evidência:** `Fabroku_Backend/src/applications/views.py:732-735` · `Fabroku_Backend/src/applications/views.py:763-770` · `Fabroku_Backend/src/applications/views.py:799-806` · `Fabroku_Backend/src/applications/views.py:836-844` · `Fabroku_Backend/src/applications/views.py:620-622` · `Fabroku_Backend/src/applications/use_cases/run_command.py:89-90`
- **O que o código faz:** run_command, migrate, loaddata e dumpdata não checam se há operação em andamento e gravam o próprio `task_id` no App. A escala checa uma lista incompleta (sem RESTARTING/STOPPING) e também grava.
- **Por que importa:** durante um deploy, rodar `migrate` faz a tela acompanhar o comando. Quando ele termina, o card "Fazendo deploy..." congela, e nem F5 resolve até o deploy acabar. Se o usuário então clica Parar para cancelar, o stop revoga o comando (já terminado), grava RUNNING e o deploy segue rodando.
- **Proposta:** usar a mesma guarda `_app_busy_response` nesses 5 endpoints (409 durante operação em andamento). No front, desabilitar o input de comando em status transitório.
- **Custo:** pequeno (~30 min) · **Risco da mudança:** baixo (só recusa o que hoje quebra o estado)
- **Certeza:** verificado
- **Decisão:** [x] aprovar  [ ] reprovar  [ ] ajustar
- **Comentário:**

## A-02 · Último a escrever vence: worker grava status final mesmo sem ser mais o dono · severidade: alta

- **Cenários:** C5, C10, C11, C13
- **Evidência:** `Fabroku_Backend/src/applications/use_cases/deploy_app.py:154-155` · `Fabroku_Backend/src/applications/use_cases/deploy_app.py:182-187` · `Fabroku_Backend/src/applications/use_cases/manage_app.py:83-89` · `Fabroku_Backend/src/applications/models.py:67-72`
- **O que o código faz:** cada worker faz `app.status = X; app.save()` no fim, sem conferir se outra ação já assumiu o app (o `task_id` mudou).
- **Por que importa:** excluir durante um deploy faz o deploy gravar RUNNING ou ERROR por cima de DELETING, e o app pisca antes de sumir. Com deploys paralelos (C10/C11), o status final é de quem terminar por último, não da última ação pedida.
- **Proposta:** gravação condicional: `App.objects.filter(id=app.id, task_id=meu_task_id).update(status=...)`. A task que perdeu a posse só registra no log ("operação substituída por outra"). Um helper único usado por deploy, manage e delete.
- **Custo:** médio (~1h) · **Risco da mudança:** médio (mexe no fim de todas as tasks; precisa de testes por task)
- **Certeza:** verificado
- **Decisão:** [x] aprovar  [ ] reprovar  [ ] ajustar
- **Comentário:**

## A-03 · Webhook de push ignora operação em andamento · severidade: alta

- **Cenários:** C10, C11, C12, C13
- **Evidência:** `Fabroku_Backend/src/infrastructure/adapters/utils/git_webhook.py:74-82` · `Fabroku_Backend/src/infrastructure/adapters/utils/git_webhook.py:119-120` · `Fabroku_Backend/src/applications/use_cases/deploy_app.py:85-91`
- **O que o código faz:** o webhook só filtra a branch e a entrega duplicada e chama `deploy_app_task.delay`. Não usa a guarda nem grava `task_id`/DEPLOYING no request (o A-02 anterior não cobriu o webhook).
- **Por que importa:** push durante restart, stop ou delete roda um deploy em paralelo no mesmo app. Dois pushes seguidos rodam dois deploys juntos. Se o Dokku recusa o segundo por lock (inferido), o app fica ERROR mesmo com o primeiro deploy ok.
- **Proposta:** webhook passa a usar `_dispatch_app_task`. Se o app estiver ocupado: em DEPLOYING, guarda o commit como "redeploy pendente" e roda ao terminar (o último push vence); em DELETING, ignora; nos demais transitórios, também guarda como pendente. Resposta ao GitHub continua 200/202.
- **Custo:** médio (~1h30, com o pendente) ou pequeno (~20 min, se só ignorar quando ocupado) · **Risco da mudança:** médio
- **Certeza:** verificado (lock do Dokku em C11: inferido)
- **Decisão:** [x] aprovar  [ ] reprovar  [ ] ajustar
- **Comentário:** opção escolhida: redeploy pendente (o último push vence). C12 (push com app parado religa o app) não foi decidido; fica como hoje.

## A-04 · Cancelar redeploy grava RUNNING sem saber o estado real · severidade: média

- **Cenários:** C3
- **Evidência:** `Fabroku_Backend/src/applications/views.py:375-397` · `Fabroku_Backend/src/applications/use_cases/deploy_app.py:117-118`
- **O que o código faz:** Parar durante DEPLOYING revoga a task com SIGTERM e grava RUNNING. O commit marcado como *pending* no GitHub nunca é resolvido.
- **Por que importa:** se o app estava STOPPED ou ERROR antes do redeploy, a tela mostra RUNNING e o app não está no ar. O check do commit no GitHub fica amarelo para sempre.
- **Proposta:** depois do revoke, consultar `dokku ps:report` (já usado em processes) para gravar RUNNING ou STOPPED real; marcar o commit como failure com "cancelado pelo usuário".
- **Custo:** pequeno (~40 min) · **Risco da mudança:** baixo
- **Certeza:** verificado (se o build continua no servidor após o SIGTERM: inferido)
- **Decisão:** [x] aprovar  [ ] reprovar  [ ] ajustar
- **Comentário:**

## A-05 · Ação recusada não dá retorno na tela · severidade: média

- **Cenários:** C1, C4 e qualquer 409/400/502
- **Evidência:** `Fabroku_Frontend/src/components/projects/AppActionsCard.vue:36` · `Fabroku_Frontend/src/components/projects/AppActionsCard.vue:48` · handlers em `[appId].vue` linhas 544-595
- **O que o código faz:** erros de iniciar/parar/reiniciar/redeploy/excluir só vão para `console.error`. Parar continua habilitado em STARTING/STOPPING/RESTARTING, onde o backend sempre responde 409.
- **Por que importa:** o usuário clica e nada acontece. Com a guarda de 409 nova, isso ficou mais comum.
- **Proposta:** mostrar a mensagem do backend num snackbar; desabilitar Parar em STARTING/STOPPING/RESTARTING; em DEPLOYING, trocar o texto para "Cancelar deploy".
- **Custo:** pequeno (~30 min) · **Risco da mudança:** baixo
- **Certeza:** verificado
- **Decisão:** [x] aprovar  [ ] reprovar  [ ] ajustar
- **Comentário:**

## A-06 · env_vars usa lista própria e reinicia dentro da request · severidade: média

- **Cenários:** C8
- **Evidência:** `Fabroku_Backend/src/applications/views.py:455-459` · `Fabroku_Backend/src/applications/views.py:505-511`
- **O que o código faz:** o 409 só cobre DEPLOYING/DELETING/STARTING. Com "reiniciar" marcado, o `ps:restart` roda síncrono na request.
- **Por que importa:** mudar variável durante um restart dispara um segundo restart junto, e a request pode ficar até ~2 min pendurada sem log no app.
- **Proposta:** trocar a lista pela guarda `_app_busy_response`. Opcional: em vez do restart síncrono, despachar `manage_app_task` restart (aparece no card e nos logs como um restart normal).
- **Custo:** pequeno (~15 min só a guarda; ~40 min com o restart assíncrono) · **Risco da mudança:** baixo
- **Certeza:** verificado
- **Decisão:** [x] aprovar  [ ] reprovar  [ ] ajustar
- **Comentário:**

## A-07 · Tela parada não vê mudança feita fora dela · severidade: baixa

- **Cenários:** C14 (outra aba, CLI, MCP, push no GitHub)
- **Evidência:** watch em `[appId].vue` linha 473 · `Fabroku_Frontend/src/modules/applications/presentation/composables/use-app-task-polling.ts:52-60`
- **O que o código faz:** fora de status transitório a página não consulta o backend.
- **Por que importa:** um push que inicia deploy, ou um restart pela CLI, não aparece até F5. O usuário pode tomar ação em cima de status velho.
- **Proposta:** `fetchApp` leve a cada 20 s enquanto a aba estiver visível (`document.visibilityState`); se virar transitório, o polling atual assume.
- **Custo:** pequeno (~20 min) · **Risco da mudança:** baixo (1 GET a cada 20 s por aba aberta)
- **Certeza:** verificado
- **Decisão:** [x] aprovar  [ ] reprovar  [ ] ajustar
- **Comentário:**

## Registro de reprovados

| ID | Motivo da reprovação | Data |
|----|----------------------|------|

## Implementação

| ID | Onde |
|----|------|
| A-01 | guarda `_app_busy_response` em run_command, migrate, loaddata, dumpdata e scale; tasks auxiliares não gravam mais `task_id` no worker; input de comando desabilitado em status transitório |
| A-02 | `applications/ownership.py` (`claim_app`, `save_if_owner`); usado por deploy, manage e delete; task substituída termina como `superseded` |
| A-03 | `applications/pending_redeploy.py`; webhook usa `dispatch_app_task` com troca atômica; app ocupado guarda o push (o último vence) e a task que termina dispara o pendente; DELETING ignora |
| A-04 | cancelar redeploy consulta `ps:report --running` (RUNNING/STOPPED, ou ERROR `RedeployCancelled` se não der para confirmar), marca o commit como falha no GitHub e descarta o redeploy pendente |
| A-05 | snackbar com a mensagem do backend; Parar desabilitado em STARTING/STOPPING/RESTARTING; "Cancelar deploy" em DEPLOYING |
| A-06 | env vars usa a guarda comum; restart vira `manage_app_task` (card e logs) em vez de rodar dentro da request |
| A-07 | `fetchApp` a cada 20 s com a aba visível e fora de operação |
| extra | `dispatch_app_task` desfaz status/`task_id` se o broker recusar a task (senão o app ficava preso numa task que nunca roda) |

