from __future__ import annotations

from typing import Type

from fabroku.domain.ports import DokkuService, OperationResult


class DeleteAppUseCase:
    """Caso de uso para deletar app no Dokku e remover do banco de dados.
    """

    def __init__(self, dokku_service: DokkuService, projeto_model: Type, user_model: Type) -> None:
        self._dokku_service = dokku_service
        self._Projeto = projeto_model
        self._User = user_model

    def execute(self, app_name: str, user_email: str) -> OperationResult:
        if not app_name or app_name.strip() == "":
            return OperationResult(False, "Nome da aplicação é obrigatório.")

        # 1. Verificar e remover do Dokku
        delete_result = self._dokku_service.delete_app(app_name=app_name.strip())
        if not delete_result.success:
            return delete_result

        # 2. Remover do banco de dados (se a app Dokku foi removida)
        try:
            user = self._User.objects.get(email=user_email)
            # Apenas remove se o usuário logado é o owner no banco
            self._Projeto.objects.filter(nome=app_name, usuario=user).delete()
        except self._User.DoesNotExist:
            # Isso não deve acontecer se a verificação de sessão foi bem-sucedida na CLI
            pass
        except self._Projeto.DoesNotExist:
            # Projeto já pode ter sido removido ou nunca existiu no banco
            pass

        return OperationResult(True, f"App '{app_name}' deletada com sucesso.")


