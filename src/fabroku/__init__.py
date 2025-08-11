"""
Fabroku CLI

Camada de aplicação para gerenciar apps no Dokku com uma arquitetura hexagonal
(Ports and Adapters).

Estrutura:
- domain: regras de negócio e contratos (ports)
- application: casos de uso
- infrastructure: adaptadores concretos (ex.: shell/ssh para Dokku)
- cli: interface de linha de comando (Click)
"""

__all__ = [
    "__version__",
]

__version__ = "0.1.0"


