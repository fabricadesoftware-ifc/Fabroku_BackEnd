---
flow: app-status-lifecycle
commit: backend b93646c · frontend 947e819
status: aguardando decisão
---

# Decisões: ciclo de status do App

Marque cada achado com **aprovar**, **reprovar** ou **ajustar** (e comente). Só os aprovados viram implementação.

## A-01 · Front não acompanha RESTARTING/STOPPING · severidade: alta

- **Evidência:** `Fabroku_Frontend/src/modules/applications/presentation/composables/use-app-task-polling.ts:18` · `Fabroku_Frontend/src/pages/projects/[projectId]/[appId].vue:469-481` · `Fabroku_Frontend/src/modules/applications/presentation/composables/use-app-actions.ts:68-92`
- **O que o código faz:** a lista de status "em andamento" tem só STARTING/DELETING/DEPLOYING. Ao receber RESTARTING ou STOPPING do backend (reload da página ou fim do polling), o watch desliga o polling. O stop nunca liga polling, e o restart finge ser STARTING no estado local.
- **Por que importa:** é a causa direta do "status fixo" na tela. Só sai com F5 depois que a task termina.
- **Proposta:** uma constante única `TRANSIENT_STATUSES` (STARTING, STOPPING, RESTARTING, DEPLOYING, DELETING), usada em polling, watch, logs e lock de processos. Restart aplica RESTARTING e stop aplica STOPPING com polling.
- **Custo:** pequeno (~30 min) · **Risco da mudança:** baixo
- **Certeza:** verificado
- **Decisão:** [ ] aprovar  [ ] reprovar  [ ] ajustar
- **Comentário:**

## A-02 · `task_id` não é gravado no request (corrida com task antiga) · severidade: alta

- **Evidência:** `Fabroku_Backend/src/applications/views.py:389-411` · `Fabroku_Backend/src/applications/use_cases/manage_app.py:56-57` · `Fabroku_Backend/src/applications/views.py:639-648`
- **O que o código faz:** a view grava o status, mas o `task_id` novo só é gravado quando o worker começa. Até lá, `get_app_status` responde sobre a task ANTERIOR (normalmente SUCCESS). O front para o polling achando que acabou.
- **Por que importa:** mesmo com A-01 corrigido, o primeiro poll pode encerrar cedo. Se a fila estiver cheia, a janela é longa.
- **Proposta:** gerar o id antes (`task_id = uuid4()`), gravar `status` + `task_id` juntos e despachar com `apply_async(task_id=...)`. Vale para start, stop, restart, redeploy e delete.
- **Custo:** pequeno (~30 min) · **Risco da mudança:** baixo
- **Certeza:** verificado
- **Decisão:** [ ] aprovar  [ ] reprovar  [ ] ajustar
- **Comentário:**

## A-03 · Falha no Dokku vira RUNNING/STOPPED · severidade: alta

- **Evidência:** `Fabroku_Backend/src/applications/use_cases/manage_app.py:77-80` · `Fabroku_Backend/src/infrastructure/adapters/ssh.py:146-166`
- **O que o código faz:** `_run_command` devolve string de erro em vez de lançar. O use case grava o status final sem checar, então o `except` nunca roda para erro de Dokku.
- **Por que importa:** restart que falhou ou estourou o timeout de 120 s aparece como RUNNING. O aluno acha que funcionou.
- **Proposta:** usar `check_dokku_output(output, ...)`, que já existe, logo após a chamada. Falha vira ERROR + `error_type='ManageAppFailed'` + `error_details`. Para restart/start, subir o timeout do comando (ex.: 600 s) via adapter dedicado.
- **Custo:** pequeno (~20 min) · **Risco da mudança:** baixo
- **Certeza:** verificado (o timeout ideal depende do tamanho dos apps: inferido)
- **Decisão:** [ ] aprovar  [ ] reprovar  [ ] ajustar
- **Comentário:**

## A-04 · Nada destrava status transitório órfão · severidade: média

- **Evidência:** `Fabroku_Backend/src/applications/use_cases/manage_app.py:88-92` · `Fabroku_Backend/src/config/settings.py:484` · `Fabroku_Backend/src/applications/views.py:639-676`
- **O que o código faz:** só o próprio worker tira o app do status transitório. Se o processo morrer (restart do worker, hard time limit, broker caindo no `.delay`), o status fica para sempre.
- **Por que importa:** é o caso "preso mesmo depois do F5".
- **Proposta:** (a) em `get_app_status`, se o app está transitório e a task está FAILURE/REVOKED, gravar ERROR; (b) task periódica (beat, a cada 5 min) que põe em ERROR apps transitórios cuja task está PENDING/STARTED há mais de 35 min; (c) se `.delay` lançar, voltar o status anterior e responder 503.
- **Custo:** médio (~1h30) · **Risco da mudança:** baixo
- **Certeza:** inferido (depende de como o worker é reiniciado em produção)
- **Decisão:** [ ] aprovar  [ ] reprovar  [ ] ajustar
- **Comentário:**

## A-05 · Start/stop/restart sem trava de concorrência · severidade: média

- **Evidência:** `Fabroku_Backend/src/applications/views.py:315-337` · `Fabroku_Backend/src/applications/views.py:389-411` · `Fabroku_Backend/src/applications/views.py:613-617`
- **O que o código faz:** redeploy e env_vars devolvem 409 em operação em andamento; start/restart não. Restart durante DEPLOYING sobrescreve o status e o `task_id`; o deploy termina e grava outro status por cima.
- **Por que importa:** clique duplo ou restart no meio do deploy deixa status e logs trocados.
- **Proposta:** 409 se o status estiver em `TRANSIENT_STATUSES`. A exceção é stop durante DEPLOYING, que continua cancelando.
- **Custo:** pequeno (~15 min) · **Risco da mudança:** baixo
- **Certeza:** verificado
- **Decisão:** [ ] aprovar  [ ] reprovar  [ ] ajustar
- **Comentário:**

## Registro de reprovados

| ID | Motivo da reprovação | Data |
|----|----------------------|------|
