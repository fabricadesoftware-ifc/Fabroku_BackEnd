from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from fabroku.infrastructure.django_bootstrap import setup_django
import random


@dataclass
class AuthUser:
	id: int
	name: str
	email: str


class AuthService:
	def __init__(self) -> None:
		setup_django()
		from core.user.infra.user_django_app.models import User  # lazy import
		self._User = User

	def register(self, name: str, email: str, password: str, matricula: Optional[str] = None) -> AuthUser:

		user = self._User.objects.create_user(email=email, password=password, name=name)
		return AuthUser(id=user.id, name=user.name, email=user.email)

	def login(self, email: str, password: str) -> Optional[AuthUser]:
		# Valida credenciais
		try:
			user = self._User.objects.get(email=email)
		except self._User.DoesNotExist:
			return None
		if not user.check_password(password):
			return None
		return AuthUser(id=user.id, name=user.name, email=user.email)

	def get_user(self, email: str) -> Optional[AuthUser]:
		try:
			user = self._User.objects.get(email=email)
			return AuthUser(id=user.id, name=user.name, email=user.email)
		except self._User.DoesNotExist:
			return None 