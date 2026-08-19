# POC local: deploy estilo Vercel para apps estáticos

Experimento isolado (branch `experiment/vercel-style-static-deploy`, pasta
`experiments/static_deploy_poc/`) para testar, **só localmente**, se o
mecanismo por trás da velocidade do Vercel — build imutável + object storage
+ troca atômica de symlink — funciona e é rápido de verdade, antes de
considerar integrar isso ao Fabroku de produção.

Nada aqui toca no código real do Fabroku_Backend (models, use cases, views).
É um script Python + `docker-compose` totalmente à parte.

## O que este POC prova (e o que não prova)

Prova:
- Que um deploy "sem container por app" é possível: build roda uma vez,
  vira arquivo estático, fica pronto pra servir sem nenhum processo/porta
  dedicado por app.
- Que a troca entre versões pode ser atômica e sem downtime: o Nginx nunca
  reinicia entre deploys, só passa a servir o novo `current` no próximo
  request.
- Que rollback pode ser instantâneo: como cada release é imutável, voltar
  pra versão anterior é só trocar o symlink de novo — sem rebuild.
- Uma ordem de grandeza real do tempo de cada etapa (build, upload,
  materialização, swap) rodando no seu ambiente.

Não prova (fora do escopo de um teste local):
- CDN/edge global de verdade (aqui é 1 Nginx local, não uma rede distribuída).
- SSL/domínio por app (usamos só `localhost:8090`).
- Como isso conviveria com quotas, autenticação e o resto do Fabroku real.
- Isolamento entre apps de tenants diferentes compartilhando o mesmo Nginx.

## Arquitetura do teste

```
Fabroku_Frontend (Vue)
        │  npm run build
        ▼
      dist/                         artefato imutável, gerado uma vez
        │  mc cp (upload)
        ▼
  MinIO (object storage local)      fonte durável do release
        │  mc cp (download)
        ▼
data/releases/<release_id>/         materializado localmente
        │  ln -sfn + mv -T (atômico)
        ▼
data/current  ──────────────────►  Nginx serve sempre de /srv/current
```

## Como rodar

Pré-requisitos: Docker Desktop rodando, Node/npm instalados (o mesmo usado
pelo `Fabroku_Frontend`).

```bash
cd experiments/static_deploy_poc

# 1. sobe o MinIO + Nginx (só precisa rodar uma vez)
docker compose up -d

# 2. build + deploy completo, com timing de cada etapa
python publish.py

# abra http://localhost:8090        -> a aplicação Vue de verdade
# abra http://localhost:8090/__release__  -> confirma qual release está no ar
```

Simular um redeploy (pulando o build, só pra medir o custo de
publish/swap isolado):

```bash
python publish.py --skip-build
```

Ver os releases publicados e qual está ativo:

```bash
python publish.py --list
```

Rollback instantâneo para um release anterior (sem rebuild):

```bash
python publish.py --rollback 20250101-120000
```

## Para desmontar

```bash
docker compose down -v
```

## Resultado medido localmente

Rodado no Windows deste ambiente, com Docker Desktop, contra o
`Fabroku_Frontend` real (`npm run build` = `type-check` + `vite build`):

| Execução                                    | build   | ensure_bucket | upload | materialize | atomic_swap | TOTAL   |
|----------------------------------------------|--------:|---------------:|-------:|------------:|------------:|--------:|
| 1ª (imagens Docker frias: `alpine`, `mc`)     | 27.04s  | 0.97s           | 2.60s  | 4.29s       | 42.03s\*    | 76.93s  |
| 2ª (imagens já em cache)                      | 25.65s  | 1.11s           | 2.34s  | 4.48s       | 1.11s       | 34.70s  |
| `--skip-build` (só publish, sem rebuild)      | —       | 1.16s           | 2.30s  | 4.34s       | 1.08s       | 8.87s   |
| `--rollback <id>` (voltar pra versão anterior)| —       | —               | —      | —           | 1.09s       | 1.09s   |

\* os 42s da 1ª troca atômica são 100% pull de imagem Docker (`alpine`),
não custo do mecanismo em si — por isso a 2ª execução é o número que
importa.

O que isso mostra: uma vez que o artefato já existe (`--skip-build`),
publicar uma nova versão inteira — subir pro storage, materializar,
trocar o ponteiro — leva **~9s**, e um **rollback é ~1s**, porque não
envolve nem storage nem rede: é só reapontar o symlink que o Nginx já
está olhando. Isso é o núcleo do que faz o Vercel parecer instantâneo:
o "deploy" caro (build) só acontece quando o código muda; a promoção
pra produção e o rollback são operações baratas e constantes,
independente de quantos releases já existem.

## Comparação com o fluxo Dokku atual

Os números do lado Dokku vêm da análise feita nas conversas anteriores
sobre o fluxo de criação/deploy de apps no Fabroku
(`applications/use_cases/create_app.py` e `deploy_app.py`), não de um
benchmark ao vivo contra um host Dokku real — isso ficaria pra uma etapa
seguinte, fora do escopo deste teste local.

| Etapa                                   | Dokku (app dinâmico)                          | Este POC (app estático)              |
|------------------------------------------|-----------------------------------------------|----------------------------------------|
| Onde o build acontece                   | dentro do container, via herokuish/buildpack   | fora do container, local (`vite build`) |
| O que "vai pro ar"                      | um container completo, precisa bootar          | arquivos estáticos, sem processo       |
| Troca de versão                         | restart/rebuild do container                   | troca de symlink (~1s, Nginx nem reinicia) |
| Rollback                                | precisa reconstruir/resubir a versão anterior  | troca o symlink de volta (~1s, instantâneo) |
| Overhead fixo por deploy                | handshakes SSH + boot de container              | upload + cópia de arquivos (~8-9s total) |
