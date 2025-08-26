from __future__ import annotations

from typing import Dict, Optional, Type
import os
import getpass

from fabroku.domain.ports import DokkuService, OperationResult


class CreateAppUseCase:
    """Caso de uso para criar uma app no Dokku e registrar no banco de dados.
    """

    def __init__(self, dokku_service: DokkuService, projeto_model: Type, user_model: Type, network_model: Type) -> None:
        self._dokku_service = dokku_service
        self._Projeto = projeto_model
        self._User = user_model
        self._Network = network_model

    def execute(
        self,
        app_name: str,
        user_email: str,
        nome: str,
        tecnologia: str,
        porta: int,
        source_url: str,
        source_type: str,
        network_name: str,
        descricao: Optional[str] = None,
        variaveis_ambiente: Optional[Dict[str, str]] = None,
    ) -> OperationResult:
        if not app_name or app_name.strip() == "":
            return OperationResult(False, "Nome da aplicação é obrigatório.")

        # 1. Obter o usuário criador
        try:
            user = self._User.objects.get(email=user_email)
        except self._User.DoesNotExist:
            return OperationResult(False, f"Usuário com email {user_email} não encontrado.")

        # 2. Obter ou criar a Network
        network, _ = self._Network.objects.get_or_create(name=network_name, defaults={'description': f'Rede para {network_name}'})

        # 3. Criar registro do Projeto no banco de dados
        projeto = self._Projeto.objects.create(
            usuario=user,
            nome=nome,
            descricao=descricao,
            tecnologia=tecnologia,
            source_type=source_type,
            source_url=source_url,
            network=network,
            porta=porta,
            variaveis_ambiente=variaveis_ambiente,
            status='rascunho',
        )

        # 4. Criar app no Dokku
        env_vars = dict(variaveis_ambiente or {})
        env_vars["FABROKU_TAG"] = env_vars.get("FABROKU_TAG") or getpass.getuser() # Usar a tag gerada/associada ao user
        
        create_result = self._dokku_service.create_app(app_name=app_name.strip(), initial_environment=env_vars)
        if not create_result.success:
            projeto.status = 'erro'
            projeto.save()
            return create_result

        # Atualizar projeto com o status do Dokku
        projeto.status = 'pronto' if create_result.success else 'erro'
        projeto.save()

        return OperationResult(True, f"Projeto '{nome}' criado e app Dokku '{app_name}' provisionada com sucesso.")


