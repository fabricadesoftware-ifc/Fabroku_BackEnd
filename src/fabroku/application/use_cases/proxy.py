from __future__ import annotations

from typing import List

from fabroku.domain.ports import DokkuService, OperationResult


class ProxyPortsSetUseCase:
    def __init__(self, dokku_service: DokkuService) -> None:
        self._dokku = dokku_service

    def execute(self, app_name: str, mappings: List[str]) -> OperationResult:
        if not app_name:
            return OperationResult(False, "Nome da app é obrigatório.")
        if not mappings:
            return OperationResult(False, "Informe ao menos um mapeamento.")
        return self._dokku.proxy_ports_set(app_name=app_name, mappings=mappings)


class ProxyPortsAddUseCase:
    def __init__(self, dokku_service: DokkuService) -> None:
        self._dokku = dokku_service

    def execute(self, app_name: str, mappings: List[str]) -> OperationResult:
        if not app_name:
            return OperationResult(False, "Nome da app é obrigatório.")
        if not mappings:
            return OperationResult(False, "Informe ao menos um mapeamento.")
        return self._dokku.proxy_ports_add(app_name=app_name, mappings=mappings)


class ProxyPortsClearUseCase:
    def __init__(self, dokku_service: DokkuService) -> None:
        self._dokku = dokku_service

    def execute(self, app_name: str) -> OperationResult:
        if not app_name:
            return OperationResult(False, "Nome da app é obrigatório.")
        return self._dokku.proxy_ports_clear(app_name=app_name)


