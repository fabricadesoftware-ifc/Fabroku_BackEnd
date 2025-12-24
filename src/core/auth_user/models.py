import unicodedata

from django.contrib.auth.models import AbstractUser
from django.db import models
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

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']
    EMAIL_FIELD = 'email'

    objects = CustomUserManager()  # type: ignore

    def __str__(self):
        return self.email + ' - ' + (self.name or 'No Name')

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'
        ordering = ['-date_joined']
