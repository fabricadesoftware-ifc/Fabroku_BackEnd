from __future__ import annotations

from typing import List, Optional
import getpass
import os

from fabroku.domain.ports import DokkuService
from core.project.infra.project_django_app.models import Projeto # Importar modelo Projeto


class ListProjectsUseCase: # Renomeado de ListAppsUseCase
	"""Lista projetos do Dokku filtradas por tag.

	Critério: projeto é do usuário se a variável de ambiente FABROKU_TAG do projeto coincide com a tag solicitada.
	Se tag não for informada, usar tag padrão do chamador (a CLI usa o email do usuário autenticado como tag padrão).
	"""
	def __init__(self, dokku_service: DokkuService, projeto_model: type[Projeto]) -> None:
		self._dokku = dokku_service
		self._Projeto = projeto_model

	def execute(self, tag: Optional[str] = None, include_all: bool = False) -> List[str]:
		if include_all:
			# Retorna todos os nomes de projetos do banco (ou Dokku, se preferir)
			return list(self._Projeto.objects.values_list('nome', flat=True))

		effective_tag = tag or os.getenv("FABROKU_TAG") or os.getenv("FABROKU_OWNER") or getpass.getuser()

		# Filtra projetos do banco de dados pelo FABROKU_TAG nas variaveis_ambiente
		# Dokku não tem um mecanismo nativo para listar apps por uma env-var arbitrária no cliente Dokku. 
		# Então, confiamos no nosso banco de dados como fonte da verdade para o 'owner'.
		filtered_projects = self._Projeto.objects.filter(
			variaveis_ambiente__FABROKU_TAG=effective_tag
		).values_list('nome', flat=True)

		return list(filtered_projects) 