from __future__ import annotations

from typing import List, Optional

from fabroku.domain.ports import DokkuService, OperationResult


class CreateRabbitMQUseCase:
    def __init__(self, dokku_service: DokkuService) -> None:
        self._dokku = dokku_service

    def execute(self, service_name: str, options: Optional[List[str]] = None) -> OperationResult:
        if not service_name:
            return OperationResult(False, "Nome do serviço é obrigatório.")
        return self._dokku.rabbitmq_create(service_name=service_name, options=options)


class LinkRabbitMQUseCase:
    def __init__(self, dokku_service: DokkuService) -> None:
        self._dokku = dokku_service

    def execute(self, service_name: str, app_name: str) -> OperationResult:
        if not service_name or not app_name:
            return OperationResult(False, "Serviço e app são obrigatórios.")
        return self._dokku.rabbitmq_link(service_name=service_name, app_name=app_name)


