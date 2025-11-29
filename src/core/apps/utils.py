import re


def slugify_dokku(name: str) -> str:
    """Converte um nome em um slug válido para Dokku."""

    name = name.lower()
    name = re.sub(r'[^a-z0-9\-]', '-', name)  # Mantém apenas a-z, 0-9 e hífen
    name = re.sub(r'-+', '-', name)  # Evita hífens duplos
    name = name.strip('-')  # Remove hífens do começo/fim
    return name
