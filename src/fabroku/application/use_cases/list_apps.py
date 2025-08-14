from __future__ import annotations

from typing import List, Optional
import getpass
import os

from fabroku.domain.ports import DokkuService


class ListAppsUseCase:
	"""Lista apps do Dokku filtradas por tag.

	Critério: app é do usuário se a variável de ambiente FABROKU_TAG da app coincide com a tag solicitada.
	Se tag não for informada, usar tag padrão do chamador (a CLI usa o email do usuário autenticado como tag padrão).
	"""
	def __init__(self, dokku_service: DokkuService) -> None:
		self._dokku = dokku_service

	def execute(self, tag: Optional[str] = None, include_all: bool = False) -> List[str]:
		apps = self._dokku.apps_list()
		if not apps:
			return []

		if include_all:
			return apps

		effective_tag = tag or os.getenv("FABROKU_TAG") or os.getenv("FABROKU_OWNER") or getpass.getuser()
		filtered: list[str] = []
		for app in apps:
			cfg = self._dokku.config_get(app, "FABROKU_TAG")
			if cfg.success:
				value = (cfg.message or "").strip()
				if value == effective_tag:
					filtered.append(app)
		return filtered 