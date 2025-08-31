from __future__ import annotations

from fabroku.domain.ports import DokkuService, OperationResult


class GetDeployLogsUseCase:
    """Caso de uso para obter os logs de deploy/build de uma aplicação Dokku.
    """

    def __init__(self, dokku_service: DokkuService) -> None:
        self._dokku_service = dokku_service

    def execute(self, app_name: str) -> OperationResult:
        if not app_name or app_name.strip() == "":
            return OperationResult(False, "Nome da aplicação é obrigatório.")
        return self._dokku_service.deploy_logs(app_name=app_name.strip())
