# ADR 0001: Logs runtime com SSE e Dokku tail compartilhado

## Status

Aceito.

## Contexto

A tela de logs runtime do Fabroku fazia polling HTTP em `/api/logs/app-runtime/` a cada poucos segundos. Cada chamada executava `dokku logs` via SSH. Em sala de aula, varias abas abertas no mesmo app multiplicavam conexoes SSH sem necessidade.

Logs runtime sao fluxo servidor-cliente: o usuario nao precisa enviar entrada ao backend. Por isso SSE e mais simples que WebSocket para este caso. WebSocket continua reservado para sessoes interativas da CLI, como `createsuperuser` e `db connect`.

## Decisao

Usaremos SSE para entregar logs runtime ao frontend e um processo dedicado `logstream` para compartilhar o tail do Dokku.

```text
Frontend SSE
  -> Backend HTTP stream
  -> Redis pub/sub + buffer
  -> processo logstream
  -> 1x dokku logs <app> --tail por app ativo
```

Quando o primeiro usuario abre logs de um app, o backend registra um assinante em Redis. O `logstream` detecta o app ativo, inicia um unico `dokku logs --tail`, publica as linhas em Redis e mantem um buffer circular. Outros usuarios do mesmo app apenas assinam o mesmo stream. Quando nao houver assinantes, o tail encerra apos uma janela curta de ociosidade.

## Implementacao

- Novo endpoint: `GET /api/logs/app-runtime-stream/?app=<id>&tail=200`.
- Eventos SSE: `snapshot`, `line`, `heartbeat`, `error`.
- Novo processo no `Procfile`: `logstream: python src/manage.py run_log_streams`.
- Redis guarda assinantes ativos, lock por app, heartbeat do runner, pub/sub e buffer circular.
- O endpoint antigo `/api/logs/app-runtime/` permanece como fallback.
- Auditoria SSH registra comando sanitizado, origem, app, usuario, task, duracao e status em tabela propria.

## Consequencias

Reduzimos o volume de SSH de "uma chamada por usuario a cada 4s" para "um tail por app ativo". A experiencia de logs fica mais fluida e o servidor recebe uma carga mais previsivel.

O custo e operar mais um processo (`logstream`) e depender de Redis para pub/sub. Se o processo nao estiver saudavel, o endpoint SSE retorna erro e o frontend usa o fallback HTTP antigo.

## Alternativas

WebSocket foi rejeitado para logs runtime porque adiciona complexidade sem necessidade de comunicacao bidirecional. Polling HTTP foi mantido somente como fallback, pois nao resolve o problema de muitas conexoes SSH quando varios alunos acompanham o mesmo app.
