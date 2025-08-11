from __future__ import annotations

import os
import shlex
import subprocess
from typing import Dict, Optional

from fabroku.domain.ports import DokkuService, OperationResult


class DokkuShellAdapter(DokkuService):
    """Adapter que integra com Dokku via comandos de shell.

    Requisitos:
    - Ter o cliente `dokku` acessível no PATH local ou via SSH (configure DOKKU_HOST para uso de ssh).
    - Para SSH remoto, defina a variável de ambiente `DOKKU_HOST` (ex.: user@dokku-host) e opcionalmente `DOKKU_SSH_OPTS`.
    """

    def __init__(self) -> None:
        self._dokku_host = os.getenv("DOKKU_HOST")
        self._ssh_opts = os.getenv("DOKKU_SSH_OPTS", "")

    def _run(self, args: list[str]) -> OperationResult:
        try:
            if self._dokku_host:
                # Executa via SSH remoto. Se conectando como usuário 'dokku', NÃO prefixe com 'dokku'.
                # Dokku usa forced-command no usuário 'dokku' e espera apenas o subcomando (ex.: apps:create).
                remote_tokens = args
                try:
                    user_part = self._dokku_host.split("@", 1)[0]
                except Exception:
                    user_part = None
                if user_part and user_part != "dokku":
                    remote_tokens = ["dokku", *args]

                ssh_cmd = [
                    "ssh",
                    * (shlex.split(self._ssh_opts) if self._ssh_opts else []),
                    self._dokku_host,
                    "--",
                    *remote_tokens,
                ]
                process = subprocess.run(
                    ssh_cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
            else:
                # Executa localmente
                process = subprocess.run(
                    ["dokku", *args],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )

            stdout = (process.stdout or "").strip()
            stderr = (process.stderr or "").strip()
            success = process.returncode == 0
            message = stdout if success else (stderr or stdout)
            return OperationResult(success, message or ("Ok" if success else "Erro desconhecido"))
        except FileNotFoundError:
            return OperationResult(False, "Comando 'dokku' não encontrado no PATH. Instale ou configure DOKKU_HOST para SSH.")
        except Exception as exc:  # pragma: no cover - fallback defensivo
            return OperationResult(False, f"Falha ao executar comando Dokku: {exc}")

    def create_app(self, app_name: str, initial_environment: Optional[Dict[str, str]] = None) -> OperationResult:
        result = self._run(["apps:create", app_name])
        if not result.success:
            return result

        if initial_environment:
            env_pairs = [f"{k}={v}" for k, v in initial_environment.items()]
            env_result = self._run(["config:set", app_name, *env_pairs])
            if not env_result.success:
                return env_result
        return OperationResult(True, f"Aplicação '{app_name}' criada com sucesso.")

    def deploy(self, app_name: str, git_url: Optional[str] = None, image: Optional[str] = None, buildpack: Optional[str] = None) -> OperationResult:
        if image:
            # Deploy via Image (recomendado quando a imagem já está publicada)
            # dokku tags:deploy app image:tag
            args = ["tags:deploy", app_name, image]
            return self._run(args)

        assert git_url, "Para deploy por git, git_url deve ser fornecida"  # validado no use case

        # Deploy via Git (zero-downtime depende de plugins/config do dokku)
        # Estratégia: `git:from-image` ou `git:from-archive` não são padrão; usamos "apps:create" (idempotente) + `git:initialize` e `git:sync`
        # Aqui, utilizamos um caminho simples: dokku git:sync app <repo> <branch>
        branch = "main"
        if "#" in git_url:
            git_url, branch = git_url.split("#", 1)
        args = ["git:sync", app_name, git_url]
        if branch:
            args.append(branch)
        if buildpack:
            # Ajuste opcional de buildpack
            set_bp = self._run(["buildpacks:set", app_name, buildpack])
            if not set_bp.success:
                return set_bp
        return self._run(args)

    def delete_app(self, app_name: str, force: bool = False) -> OperationResult:
        args = ["apps:destroy", app_name]
        if force:
            args.append("--force")
        return self._run(args)

    # Plugins
    def plugin_install(self, plugin_git_url: str, name: Optional[str] = None) -> OperationResult:
        args = ["plugin:install", plugin_git_url]
        if name:
            args.append(name)
        return self._run(args)

    # Postgres
    def postgres_create(self, service_name: str, options: Optional[list[str]] = None) -> OperationResult:
        args = ["postgres:create", service_name]
        if options:
            args.extend(options)
        return self._run(args)

    def postgres_link(self, service_name: str, app_name: str) -> OperationResult:
        return self._run(["postgres:link", service_name, app_name])

    # RabbitMQ
    def rabbitmq_create(self, service_name: str, options: Optional[list[str]] = None) -> OperationResult:
        args = ["rabbitmq:create", service_name]
        if options:
            args.extend(options)
        return self._run(args)

    def rabbitmq_link(self, service_name: str, app_name: str) -> OperationResult:
        return self._run(["rabbitmq:link", service_name, app_name])

    # Config
    def config_set(self, app_name: str, env_vars: dict[str, str]) -> OperationResult:
        pairs = [f"{k}={v}" for k, v in env_vars.items()]
        return self._run(["config:set", app_name, *pairs])

    # Proxy / Ports
    def proxy_ports_set(self, app_name: str, mappings: list[str]) -> OperationResult:
        # mappings: ["http:80:5000", "https:443:5000"]
        return self._run(["proxy:ports-set", app_name, *mappings])

    def proxy_ports_add(self, app_name: str, mappings: list[str]) -> OperationResult:
        return self._run(["proxy:ports-add", app_name, *mappings])

    def proxy_ports_clear(self, app_name: str) -> OperationResult:
        return self._run(["proxy:ports-clear", app_name])


