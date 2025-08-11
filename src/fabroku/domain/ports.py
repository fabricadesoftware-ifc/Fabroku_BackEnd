from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Protocol, List


@dataclass(frozen=True)
class OperationResult:
    success: bool
    message: str


class DokkuService(Protocol):
    """Porta (contrato) para integração com Dokku.

    Implementações podem ser via shell, SSH, HTTP, etc.
    """

    def create_app(self, app_name: str, initial_environment: Optional[Dict[str, str]] = None) -> OperationResult:  # noqa: D401 - simples
        ...

    def deploy(self, app_name: str, git_url: Optional[str] = None, image: Optional[str] = None, buildpack: Optional[str] = None) -> OperationResult:  # noqa: D401 - simples
        ...

    def delete_app(self, app_name: str, force: bool = False) -> OperationResult:  # noqa: D401 - simples
        ...

    # Plugins
    def plugin_install(self, plugin_git_url: str, name: Optional[str] = None) -> OperationResult:
        ...

    # Postgres service
    def postgres_create(self, service_name: str, options: Optional[List[str]] = None) -> OperationResult:
        ...

    def postgres_link(self, service_name: str, app_name: str) -> OperationResult:
        ...

    # RabbitMQ service
    def rabbitmq_create(self, service_name: str, options: Optional[List[str]] = None) -> OperationResult:
        ...

    def rabbitmq_link(self, service_name: str, app_name: str) -> OperationResult:
        ...

    # App config
    def config_set(self, app_name: str, env_vars: Dict[str, str]) -> OperationResult:
        ...

    # Proxy / Ports
    def proxy_ports_set(self, app_name: str, mappings: List[str]) -> OperationResult:
        ...

    def proxy_ports_add(self, app_name: str, mappings: List[str]) -> OperationResult:
        ...

    def proxy_ports_clear(self, app_name: str) -> OperationResult:
        ...


