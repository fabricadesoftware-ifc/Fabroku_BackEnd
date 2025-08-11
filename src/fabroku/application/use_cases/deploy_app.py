from __future__ import annotations

from typing import Optional

from fabroku.domain.ports import DokkuService, OperationResult


class DeployAppUseCase:
    """Caso de uso para realizar deploy.

    Observação:
    - Uma das opções `git_url` ou `image` deve ser fornecida.
    - Em caso de ambos definidos, priorizamos `image` (deploy por imagem é determinístico e rápido).
    """

    def __init__(self, dokku_service: DokkuService) -> None:
        self._dokku_service = dokku_service

    def execute(
        self,
        app_name: str,
        git_url: Optional[str] = None,
        image: Optional[str] = None,
        buildpack: Optional[str] = None,
    ) -> OperationResult:
        if not app_name or app_name.strip() == "":
            return OperationResult(False, "Nome da aplicação é obrigatório.")

        if not git_url and not image:
            return OperationResult(False, "Informe --git-url ou --image para realizar o deploy.")

        # Se ambos fornecidos, prioriza imagem
        if image:
            return self._dokku_service.deploy(app_name=app_name.strip(), image=image.strip(), buildpack=buildpack)

        return self._dokku_service.deploy(app_name=app_name.strip(), git_url=git_url.strip() if git_url else None, buildpack=buildpack)


