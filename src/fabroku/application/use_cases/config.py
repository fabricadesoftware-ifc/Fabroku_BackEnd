from __future__ import annotations

from typing import Dict

from fabroku.domain.ports import DokkuService, OperationResult


class ConfigSetUseCase:
    def __init__(self, dokku_service: DokkuService) -> None:
        self._dokku = dokku_service

    def execute(self, app_name: str, env_vars: Dict[str, str]) -> OperationResult:
        if not app_name:
            return OperationResult(False, "Nome da app é obrigatório.")
        if not env_vars:
            return OperationResult(False, "Informe ao menos uma variável.")
        return self._dokku.config_set(app_name=app_name, env_vars=env_vars)


