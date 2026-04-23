from django.db import models


class AllowedEmailManager(models.Manager):
    """Manager para verificação de emails permitidos."""

    def is_email_allowed(self, email: str) -> bool:
        """
        Verifica se um email específico está na whitelist.
        """
        return self.filter(email__iexact=email, is_active=True).exists()

    def get_active_emails(self):
        """Retorna todos os emails ativos."""
        return self.filter(is_active=True)


class AllowedEmail(models.Model):
    """
    Modelo para armazenar emails de professores/funcionários
    que têm permissão para acessar o sistema.
    """

    email = models.EmailField(
        'E-mail',
        unique=True,
        db_index=True,
        help_text='Email do professor/funcionário autorizado',
    )
    name = models.CharField(
        'Nome',
        max_length=255,
        blank=True,
        null=True,
        help_text='Nome do professor/funcionário (opcional)',
    )
    is_active = models.BooleanField(
        'Ativo',
        default=True,
        help_text='Se desativado, o email não terá mais acesso',
    )
    notes = models.TextField(
        'Observações',
        blank=True,
        null=True,
        help_text='Observações sobre este acesso',
    )
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    objects = AllowedEmailManager()

    class Meta:
        verbose_name = 'Email Permitido'
        verbose_name_plural = 'Emails Permitidos'
        ordering = ['email']

    def __str__(self):
        if self.name:
            return f'{self.name} <{self.email}>'
        return self.email
