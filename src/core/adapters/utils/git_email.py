from typing import TypedDict


class EmailData(TypedDict):
    email: str
    verified: bool


def verify_git_email(emails: list[EmailData]) -> str | None:
    """
    Verifica se o usuário tem um email válido para acesso.

    Ordem de verificação:
    1. Email de estudante do IFC (@estudantes.ifc.edu.br)
    2. Email na whitelist de professores/funcionários (banco de dados)

    Retorna o email verificado ou None se não tiver acesso.
    """
    # Import aqui para evitar circular import
    from core.auth_user.allowed_emails.models import AllowedEmail

    verified_emails = [e for e in emails if e['verified']]

    # 1. Primeiro verifica se é email de estudante do IFC
    student_email = next(
        (e['email'] for e in verified_emails if e['email'].endswith('@estudantes.ifc.edu.br')),
        None,
    )
    if student_email:
        return student_email

    # 2. Verifica se algum email verificado está na whitelist
    for email_data in verified_emails:
        if AllowedEmail.objects.filter(email=email_data['email']).exists():
            return email_data['email']

    return None
