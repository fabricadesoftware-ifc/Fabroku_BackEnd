from __future__ import annotations

from fabroku.domain.ports import DokkuService, OperationResult


class GetAppLogsUseCase:
    """Caso de uso para obter os logs de uma aplicação Dokku.
    """

    def __init__(self, dokku_service: DokkuService) -> None:
        self._dokku_service = dokku_service

    def execute(self, app_name: str, tail: int = 50) -> OperationResult:
        if not app_name or app_name.strip() == "":
            return OperationResult(False, "Nome da aplicação é obrigatório.")
        return self._dokku_service.logs_app(app_name=app_name.strip(), tail=tail)
