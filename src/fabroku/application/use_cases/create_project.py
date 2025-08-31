from __future__ import annotations

from typing import Dict, Optional, TYPE_CHECKING

from fabroku.domain.ports import DokkuService, OperationResult

if TYPE_CHECKING:
	from core.project.infra.project_django_app.models import Projeto, Network
	from core.user.infra.user_django_app.models import User


class CreateProjectUseCase:
	"""Caso de uso para criar um Projeto no Dokku e persistir no banco de dados.

	Ele cria a app no Dokku e o registro correspondente no Django.
	"""
	def __init__(self, dokku_service: DokkuService, projeto_model: type[Projeto], user_model: type[User], network_model: type[Network]) -> None:
		self._dokku_service = dokku_service
		self._Projeto = projeto_model
		self._User = user_model
		self._Network = network_model

	def execute(
		self,
		app_name: str,
		user_email: str,
		nome: str,
		descricao: str,
		tecnologia: str,
		source_type: str,
		source_url: str,
		network_name: str,
		porta: int,
		variaveis_ambiente: Optional[Dict[str, str]] = None,
	) -> OperationResult:
		if not app_name or not nome or not user_email or not tecnologia or not source_type or not source_url or not network_name or not porta:
			return OperationResult(False, "Todos os campos obrigatórios (nome, user_email, tecnologia, source_type, source_url, network, porta) devem ser fornecidos.")

		try:
			user = self._User.objects.get(email=user_email)
		except self._User.DoesNotExist:
			return OperationResult(False, f"Usuário com email {user_email} não encontrado.")

		# Encontra ou cria a rede
		network_obj, _ = self._Network.objects.get_or_create(name=network_name, defaults={'description': f"Rede criada para o projeto {nome}"})

		# Cria o Projeto no Dokku primeiro
		create_dokku_app_result = self._dokku_service.create_app(app_name=app_name, initial_environment=variaveis_ambiente)
		if not create_dokku_app_result.success:
			return create_dokku_app_result

		# Persiste no banco de dados Django
		try:
			projeto = self._Projeto.objects.create(
				usuario=user,
				nome=nome,
				descricao=descricao,
				tecnologia=tecnologia,
				source_type=source_type,
				source_url=source_url,
				network=network_obj,
				porta=porta,
				variaveis_ambiente=variaveis_ambiente,
				status="rascunho", # Estado inicial conforme solicitado
			)
			return OperationResult(True, f"Projeto '{projeto.nome}' criado com sucesso. App Dokku: '{app_name}'.")
		except Exception as exc:
			# TODO: Se a criação no Dokku falhar após o Django, precisamos de um rollback ou um estado de erro mais explícito.
			return OperationResult(False, f"Falha ao criar projeto: {exc}") 