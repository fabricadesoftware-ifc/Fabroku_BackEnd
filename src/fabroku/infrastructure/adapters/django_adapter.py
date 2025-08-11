from __future__ import annotations

from typing import Dict, Optional

from fabroku.domain.ports import DokkuService, OperationResult


class DjangoIntegratedDokkuService(DokkuService):
    """Exemplo de adapter para integrar com a API/ORM Django deste projeto.

    Observação:
    - Este adapter é um exemplo e pode ser expandido para persistir estado do deploy
      no modelo `Projeto` em `core.project.infra.project_django_app`.
    - Ele delega o trabalho real para outro adapter (ex.: shell) e em seguida
      sincroniza com o Django (quando desejado).
    """

    def __init__(self, wrapped: DokkuService) -> None:
        self._wrapped = wrapped

    def create_app(self, app_name: str, initial_environment: Optional[Dict[str, str]] = None) -> OperationResult:
        result = self._wrapped.create_app(app_name, initial_environment)
        # TODO: Exemplificar integração com Django (persistência)
        return result

    def deploy(self, app_name: str, git_url: Optional[str] = None, image: Optional[str] = None, buildpack: Optional[str] = None) -> OperationResult:
        result = self._wrapped.deploy(app_name, git_url, image, buildpack)
        # TODO: Ex: atualizar `url_deploy` ou `status` no modelo Projeto
        return result

    def delete_app(self, app_name: str, force: bool = False) -> OperationResult:
        result = self._wrapped.delete_app(app_name, force)
        # TODO: Ex: marcar como removido no Django
        return result


