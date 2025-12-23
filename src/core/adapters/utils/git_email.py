from typing import TypedDict


class EmailData(TypedDict):
    email: str
    verified: bool


def verify_git_email(emails: list[EmailData]) -> str | None:
    return next(
        (e['email'] for e in emails if e['email'].endswith('@estudantes.ifc.edu.br') and e['verified']),
        None,
    )
