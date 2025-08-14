from __future__ import annotations

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def setup_django() -> None:
	"""Inicializa o Django para uso de ORM a partir da CLI.

	- Usa DJANGO_SETTINGS_MODULE se definido; caso contrário, assume `django_project.settings`.
	- Respeita variáveis de ambiente (.env) já carregadas pelo dotenv no CLI.
	"""
	if not os.environ.get("DJANGO_SETTINGS_MODULE"):
		os.environ["DJANGO_SETTINGS_MODULE"] = "django_project.settings"
	import django  # import tardio
	django.setup() 