from typing import TypedDict

from django.conf import settings


class EmailData(TypedDict, total=False):
    email: str
    verified: bool
    primary: bool


def _normalize_domain(domain: str) -> str:
    return domain.strip().lower().lstrip('@')


def _email_domain(email: str) -> str:
    return email.rsplit('@', 1)[-1].lower() if '@' in email else ''


def _is_allowed_domain(email: str) -> bool:
    allowed_domains = [_normalize_domain(domain) for domain in settings.AUTH_ALLOWED_EMAIL_DOMAINS]
    return _email_domain(email) in allowed_domains


def _prefer_primary(emails: list[EmailData]) -> list[EmailData]:
    return sorted(emails, key=lambda item: not item.get('primary', False))


def verify_git_email(emails: list[EmailData]) -> str | None:
    """
    Verifica se o usuario tem um email valido para acesso nesta instalacao.

    Ordem de verificacao:
    1. Email verificado com dominio configurado em AUTH_ALLOWED_EMAIL_DOMAINS.
    2. Email verificado liberado manualmente em AllowedEmail.
    3. Qualquer email verificado, se AUTH_ALLOW_ALL_VERIFIED_EMAILS=True.

    Retorna o email aprovado ou None se nao tiver acesso.
    """
    # Import aqui para evitar circular import.
    from core.auth_user.allowed_emails.models import AllowedEmail

    verified_emails = _prefer_primary([email for email in emails if email.get('verified') and email.get('email')])

    domain_email = next(
        (email['email'] for email in verified_emails if _is_allowed_domain(email['email'])),
        None,
    )
    if domain_email:
        return domain_email

    for email_data in verified_emails:
        if AllowedEmail.objects.is_email_allowed(email_data['email']):
            return email_data['email']

    if settings.AUTH_ALLOW_ALL_VERIFIED_EMAILS and verified_emails:
        return verified_emails[0]['email']

    return None
