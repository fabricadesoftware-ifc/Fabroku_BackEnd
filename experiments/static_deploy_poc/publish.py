"""POC local: deploy estilo Vercel para o Fabroku_Frontend.

Modelo testado (nada disto toca no Fabroku_Backend real, e' 100% isolado
dentro de experiments/static_deploy_poc):

    1. Build local do Vue (vite build) -> artefato imutavel em dist/.
    2. Upload do artefato para um object storage (MinIO local, via `mc`).
    3. Materializacao do release em data/releases/<release_id>/ (bind mount
       compartilhado com o Nginx).
    4. Troca atomica do symlink data/current -> data/releases/<release_id>.
       O Nginx serve sempre de /srv/current e nunca precisa de reload: o
       proximo request depois da troca ja serve a nova versao.

Uso:
    docker compose up -d                  # sobe minio + nginx uma vez
    python publish.py                     # build + deploy completo, com timing
    python publish.py --skip-build        # redeploy do dist/ ja existente
    python publish.py --list              # lista releases publicados
    python publish.py --rollback <id>     # troca o symlink para um release anterior (sem build)
"""
import argparse
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / 'data'
RELEASES_DIR = DATA_DIR / 'releases'
NETWORK = 'static_poc_net'
MINIO_ALIAS_ENV = {'MC_HOST_local': 'http://fabroku:fabroku12345@minio:9000'}
BUCKET = 'static-apps'
APP_KEY = 'fabroku-frontend'


@dataclass
class Timings:
    steps: list[tuple[str, float]] = field(default_factory=list)

    def record(self, label: str, seconds: float) -> None:
        self.steps.append((label, seconds))

    def report(self) -> None:
        print('\n--- Tempo por etapa ---')
        total = 0.0
        for label, seconds in self.steps:
            print(f'{label:<32} {seconds:7.2f}s')
            total += seconds
        print(f'{"TOTAL":<32} {total:7.2f}s')


def run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None) -> float:
    """Executa um comando, mede o tempo e falha alto em caso de erro.

    Resolve o executavel via shutil.which: no Windows, `npm`/`docker` reais
    sao `npm.cmd`/`docker.exe`, e subprocess.run sem shell=True nao aplica
    a busca por PATHEXT que o cmd.exe faria.
    """
    resolved = shutil.which(cmd[0]) or cmd[0]
    started = time.monotonic()
    result = subprocess.run(
        [resolved, *cmd[1:]], cwd=cwd, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace'
    )
    elapsed = time.monotonic() - started
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f'Comando falhou ({result.returncode}): {" ".join(cmd)}')
    return elapsed


def docker_path(path: Path) -> str:
    """Docker Desktop on Windows expects forward slashes in -v mount specs."""
    return str(path).replace('\\', '/')


def docker_run(args: list[str], *, network: str | None = NETWORK, mc_env: bool = False) -> list[str]:
    base = ['docker', 'run', '--rm']
    if network:
        base += ['--network', network]
    if mc_env:
        # -e propaga a env PRA DENTRO do container; setar no subprocess.run
        # (env=...) so afeta o processo `docker` no host, nao o container.
        for key, value in MINIO_ALIAS_ENV.items():
            base += ['-e', f'{key}={value}']
    return base + args


def build_frontend(frontend_dir: Path) -> float:
    print(f'==> Buildando {frontend_dir.name} (npm run build)...')
    return run(['npm', 'run', 'build'], cwd=frontend_dir)


def ensure_bucket() -> float:
    print('==> Garantindo bucket no MinIO...')
    return run(docker_run(['minio/mc', 'mb', '--ignore-existing', f'local/{BUCKET}'], mc_env=True))


def upload_to_storage(dist_dir: Path, release_id: str) -> float:
    print('==> Subindo artefato imutavel para o object storage (MinIO)...')
    mount = f'{docker_path(dist_dir)}:/upload:ro'
    return run(
        docker_run(
            ['-v', mount, 'minio/mc', 'cp', '-r', '/upload/', f'local/{BUCKET}/{APP_KEY}/{release_id}/'],
            mc_env=True,
        )
    )


def materialize_release(release_id: str) -> float:
    print('==> Materializando o release a partir do object storage...')
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    mount = f'{docker_path(DATA_DIR)}:/srv'
    return run(
        docker_run(
            ['-v', mount, 'minio/mc', 'cp', '-r', f'local/{BUCKET}/{APP_KEY}/{release_id}/', f'/srv/releases/{release_id}/'],
            mc_env=True,
        )
    )


def atomic_swap(release_id: str) -> float:
    print(f'==> Troca atomica: current -> releases/{release_id}')
    release_path = RELEASES_DIR / release_id
    if not release_path.exists():
        raise SystemExit(f'Release {release_id} nao existe em {RELEASES_DIR}')

    mount = f'{docker_path(DATA_DIR)}:/srv'
    script = (
        f'ln -sfn releases/{release_id} /srv/current_tmp && '
        f'mv -T /srv/current_tmp /srv/current'
    )
    return run(docker_run(['-v', mount, 'alpine', 'sh', '-c', script], network=None))


def list_releases() -> None:
    releases = sorted(p for p in RELEASES_DIR.iterdir() if p.is_dir()) if RELEASES_DIR.exists() else []
    if not releases:
        print('Nenhum release publicado ainda.')
        return

    current_link = DATA_DIR / 'current'
    current_target = current_link.resolve().name if current_link.is_symlink() else None

    print('Releases disponiveis:')
    for release in releases:
        marker = ' <- current' if release.name == current_target else ''
        print(f'  {release.name}{marker}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        '--frontend-dir',
        type=Path,
        default=HERE.parents[2] / 'Fabroku_Frontend',
        help='Caminho do Fabroku_Frontend (default: pasta irma dentro de Documents/Fabroku)',
    )
    parser.add_argument('--skip-build', action='store_true', help='Reusa o dist/ existente (simula redeploy rapido)')
    parser.add_argument('--rollback', metavar='RELEASE_ID', help='So troca o symlink current para um release ja publicado')
    parser.add_argument('--list', action='store_true', help='Lista releases publicados e sai')
    args = parser.parse_args()

    if args.list:
        list_releases()
        return

    timings = Timings()

    if args.rollback:
        timings.record('atomic_swap (rollback)', atomic_swap(args.rollback))
        timings.report()
        print(f'\nRollback concluido para {args.rollback}. Confira http://localhost:8090/__release__')
        return

    dist_dir = args.frontend_dir / 'dist'
    release_id = time.strftime('%Y%m%d-%H%M%S')

    if not args.skip_build:
        timings.record('npm run build', build_frontend(args.frontend_dir))
    elif not dist_dir.exists():
        raise SystemExit(f'--skip-build passado mas {dist_dir} nao existe. Rode sem --skip-build primeiro.')

    (dist_dir / '__release__').write_text(release_id, encoding='utf-8')

    timings.record('ensure_bucket', ensure_bucket())
    timings.record('upload_to_storage', upload_to_storage(dist_dir, release_id))
    timings.record('materialize_release', materialize_release(release_id))
    timings.record('atomic_swap', atomic_swap(release_id))

    timings.report()
    print(f'\nDeploy concluido: {release_id}')
    print('Confira: http://localhost:8090  e  http://localhost:8090/__release__')


if __name__ == '__main__':
    main()
