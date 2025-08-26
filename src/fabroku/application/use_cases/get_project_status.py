from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from core.project.infra.project_django_app.models import Projeto


@dataclass
class ProjectStatus:
	name: str
	ready: str
	estado: str # Alterado de 'available' para 'estado'
	age: str


class GetProjectStatusUseCase:
	"""Caso de uso para obter o status de um projeto.

	Retorna o status formatado conforme o padrão solicitado.
	"""
	def __init__(self, projeto_model: type[Projeto]) -> None:
		self._Projeto = projeto_model

	def execute(self, project_name: str, user_email: str) -> Optional[ProjectStatus]:
		try:
			projeto = self._Projeto.objects.get(nome=project_name, usuario__email=user_email)

			name = projeto.nome
			ready_status = "1/1" if projeto.status in ['pronto', 'em_andamento'] else "0/1"
			estado = projeto.status.capitalize() # Capitaliza a primeira letra

			age = (datetime.now(timezone.utc) - projeto.data_criacao).total_seconds()
			age_minutes = int(age / 60)
			age_str = f"{age_minutes}m" # Formato simples por enquanto
			# TODO: Melhorar formatação da idade (horas, dias, etc.)

			return ProjectStatus(name=name, ready=ready_status, estado=estado, age=age_str)
		except self._Projeto.DoesNotExist:
			return None 