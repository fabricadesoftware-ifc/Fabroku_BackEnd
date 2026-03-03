import secrets
import unicodedata

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Import do modelo AllowedEmail para que seja detectado pelas migrations
from .managers import CustomUserManager


def remove_accent(text):
    text_normal = unicodedata.normalize('NFKD', text)
    text_without_accent = ''.join(c for c in text_normal if not unicodedata.combining(c))
    return text_without_accent


class User(AbstractUser):
    username = None
    email = models.EmailField(_('e-mail address'), unique=True, db_index=True)
    avatar_url = models.URLField(max_length=500, null=True, blank=True)
    name = models.CharField(max_length=255, null=True, db_index=True)
    password_reset_token = models.CharField(_('Password Reset Token'), max_length=255, blank=True, null=True)
    password_reset_token_created = models.DateTimeField(_('Password Reset Token Created'), blank=True, null=True)
    git_token = models.CharField(max_length=255, null=True, blank=True)
    is_fabric = models.BooleanField(
        _('membro da fábrica'),
        default=False,
        help_text=_('Indica se o usuário é membro da Fábrica de Software. Membros podem personalizar nomes de apps.'),
    )

    # Limites personalizados (None = usar padrão do role)
    custom_max_apps = models.PositiveIntegerField(
        _('limite personalizado de apps'),
        null=True,
        blank=True,
        help_text=_('Sobrescreve o limite padrão de apps para este usuário. Deixe vazio para usar o padrão do perfil.'),
    )
    custom_max_services = models.PositiveIntegerField(
        _('limite personalizado de serviços'),
        null=True,
        blank=True,
        help_text=_('Sobrescreve o limite padrão de serviços para este usuário. Deixe vazio para usar o padrão do perfil.'),
    )

    # Limites padrão por perfil
    DEFAULT_MAX_APPS = 3
    DEFAULT_MAX_SERVICES = 2
    FABRIC_MAX_APPS = 5
    FABRIC_MAX_SERVICES = 3

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']
    EMAIL_FIELD = 'email'

    objects = CustomUserManager()  # type: ignore

    @property
    def max_apps(self) -> int | None:
        """Retorna o limite máximo de apps do usuário. None = sem limite (admin)."""
        if self.is_superuser:
            return None  # Sem limite
        if self.custom_max_apps is not None:
            return self.custom_max_apps
        if self.is_fabric:
            return self.FABRIC_MAX_APPS
        return self.DEFAULT_MAX_APPS

    @property
    def max_services(self) -> int | None:
        """Retorna o limite máximo de serviços do usuário. None = sem limite (admin)."""
        if self.is_superuser:
            return None  # Sem limite
        if self.custom_max_services is not None:
            return self.custom_max_services
        if self.is_fabric:
            return self.FABRIC_MAX_SERVICES
        return self.DEFAULT_MAX_SERVICES

    @property
    def apps_count(self) -> int:
        """Conta o total de apps em projetos do usuário."""
        from core.apps.models import App  # noqa: PLC0415
        return App.objects.filter(project__users=self).count()

    @property
    def services_count(self) -> int:
        """Conta o total de serviços em projetos do usuário."""
        from core.apps.models import Service  # noqa: PLC0415
        return Service.objects.filter(project__users=self).count()

    def can_create_app(self) -> bool:
        """Verifica se o usuário pode criar mais apps."""
        limit = self.max_apps
        if limit is None:
            return True
        return self.apps_count < limit

    def can_create_service(self) -> bool:
        """Verifica se o usuário pode criar mais serviços."""
        limit = self.max_services
        if limit is None:
            return True
        return self.services_count < limit

    def __str__(self):
        return self.email + ' - ' + (self.name or 'No Name')

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'
        ordering = ['-date_joined']


class CLIToken(models.Model):
    """Token de autenticação para a CLI Fabroku."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cli_tokens',
        verbose_name=_('usuário'),
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        editable=False,
    )
    name = models.CharField(
        _('nome do dispositivo'),
        max_length=100,
        default='CLI',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_hex(32)
        super().save(*args, **kwargs)

    def touch(self):
        """Atualiza last_used_at."""
        self.last_used_at = timezone.now()
        self.save(update_fields=['last_used_at'])

    def __str__(self):
        return f'{self.user.email} — {self.name} ({self.token[:8]}...)'

    class Meta:
        verbose_name = 'Token CLI'
        verbose_name_plural = 'Tokens CLI'
        ordering = ['-created_at']
