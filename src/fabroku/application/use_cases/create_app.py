from __future__ import annotations

from typing import Dict, Optional

from fabroku.domain.ports import DokkuService, OperationResult


class CreateAppUseCase:
    """Caso de uso para criar uma app no Dokku.

    Como adicionar um novo caso de uso:
    - Defina os dados de entrada/saída no método `execute`.
    - Use apenas a port `DokkuService` (ou outras ports) para acessar infraestrutura.
    - Não importe/adapte nada específico de CLI aqui.
    """

    def __init__(self, dokku_service: DokkuService) -> None:
        self._dokku_service = dokku_service

    def execute(self, app_name: str, initial_environment: Optional[Dict[str, str]] = None) -> OperationResult:
        if not app_name or app_name.strip() == "":
            return OperationResult(False, "Nome da aplicação é obrigatório.")
        return self._dokku_service.create_app(app_name=app_name.strip(), initial_environment=initial_environment)


