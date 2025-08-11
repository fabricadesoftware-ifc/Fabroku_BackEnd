from __future__ import annotations

from fabroku.domain.ports import DokkuService, OperationResult


class DeleteAppUseCase:
    """Caso de uso para deletar app no Dokku."""

    def __init__(self, dokku_service: DokkuService) -> None:
        self._dokku_service = dokku_service

    def execute(self, app_name: str, force: bool = False) -> OperationResult:
        if not app_name or app_name.strip() == "":
            return OperationResult(False, "Nome da aplicação é obrigatório.")
        return self._dokku_service.delete_app(app_name=app_name.strip(), force=force)


