from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from fabroku.domain.ports import DokkuService, OperationResult

if TYPE_CHECKING:
	from core.project.infra.project_django_app.models import Projeto


class DeployAppUseCase:
    """Caso de uso para realizar deploy.

    Observação:
    - Uma das opções `git_url` ou `image` deve ser fornecida.
    - Em caso de ambos definidos, priorizamos `image` (deploy por imagem é determinístico e rápido).
    """

    def __init__(self, dokku_service: DokkuService, projeto_model: type) -> None:
        self._dokku_service = dokku_service
        self._Projeto = projeto_model

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

        # Obter o projeto do banco de dados
        try:
            projeto = self._Projeto.objects.get(nome=app_name)
        except self._Projeto.DoesNotExist:
            return OperationResult(False, f"Projeto '{app_name}' não encontrado no banco de dados.")

        deploy_result: OperationResult

        # Se ambos fornecidos, prioriza imagem
        if image:
            deploy_result = self._dokku_service.deploy(app_name=app_name.strip(), image=image.strip(), buildpack=buildpack)
        else:
            deploy_result = self._dokku_service.deploy(app_name=app_name.strip(), git_url=git_url.strip() if git_url else None, buildpack=buildpack)

        # Atualizar o status do projeto no banco de dados com base no resultado do deploy
        if deploy_result.success:
            projeto.status = "pronto"
        else:
            projeto.status = "erro"
        projeto.save()

        return deploy_result


