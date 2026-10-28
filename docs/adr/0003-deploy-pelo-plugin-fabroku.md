# ADR 0003: Deploy pelo plugin fabroku, fora da sessão SSH

## Status

Aceito em 28/10/2026, aprovado pelo orientador. Ligado por
`DOKKU_REMOTE_DEPLOY_PLUGIN` (padrão desligado).

## Contexto

O worker fazia o build rodando `dokku git:sync --build` numa sessão SSH com PTY e
lendo a saída até o fim. Se a sessão cai, o Dokku morre junto. Isso acontecia ao
cancelar o deploy (SIGTERM na task), ao reiniciar o worker e em quedas de rede.
Em 28/10 deixou um container de `release` parado preso ao volume de cache do app
`babycorporation-backend`, e `apps:destroy` passou a falhar com "volume is in use".

O plano completo está em `Fabroku_Plugin/docs/PLANO.md`.

## Decisão

Um plugin Dokku (`Fabroku_Plugin`, comandos `fabroku:*`) inicia o build com
`setsid`, fora da sessão SSH, e responde na hora. O Fabroku:

1. Chama `fabroku:deploy <app> <git-url> <branch> <deploy-id>`, com `deploy-id`
   igual ao `task_id` da task do Celery.
2. Lê o log com `fabroku:deploy-log <deploy-id> <offset>` a cada 2 s, sem gravar
   auditoria SSH por leitura, e repassa cada linha ao `on_line` como antes.
3. Usa o exit code do build como resultado, em vez de procurar marcadores de erro
   no log.
4. Ao cancelar, chama `fabroku:deploy-cancel`, que para o build e roda
   `dokku cleanup`.
5. Se o worker morreu, `get_app_status` consulta `fabroku:deploy-status` (no
   máximo a cada 30 s por app). Build terminado há mais de 5 min com o App ainda
   DEPLOYING: grava RUNNING (sucesso com domínio) ou ERROR `RemoteDeployOrphaned`.

Só `DokkuGitMixin.sync_git_streaming` muda de implementação; os use cases só
passam o `deploy_id`. Sem o plugin, ou se `fabroku:version` falhar, o caminho
antigo continua.

## Consequências

- O build não morre mais com a sessão SSH; o log completo fica no servidor em
  `/var/lib/dokku/data/fabroku/deploys/<id>/`, apagado pelo `fabroku:gc`.
- Um deploy longo faz uma conexão SSH a cada 2 s em vez de uma conexão aberta.
- O plugin é mais uma peça para instalar e atualizar no servidor.
- Confirmado no servidor (Debian 13, Dokku 0.38.27) que um processo iniciado com
  `setsid` sobrevive à queda de uma sessão SSH com PTY.
