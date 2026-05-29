# Fabroku Backend

## Configuracao por instalacao

O Fabroku preserva os defaults da instalacao IFC, mas pode ser executado em
outros ambientes usando variaveis de ambiente:

- `AUTH_ALLOWED_EMAIL_DOMAINS`: dominios de email GitHub verificados que podem entrar. Default: `estudantes.ifc.edu.br`.
- `AUTH_ALLOW_ALL_VERIFIED_EMAILS`: quando `True`, qualquer email verificado do GitHub pode entrar.
- `AUTH_EMAIL_REJECTION_MESSAGE`: mensagem exibida quando o email nao passa na politica de acesso.
- `FABROKU_ORGANIZATION_NAME`: nome da organizacao exibido no frontend. Default: `Fábrica de Software`.
- `FABROKU_PRIVILEGED_ROLE_LABEL`: label publico para usuarios com `is_fabric=True`.
- `FABROKU_REGULAR_ROLE_LABEL`: label publico para usuarios comuns.
- `FABROKU_APP_DOMAIN_SUFFIX`: sufixo mostrado na criacao de apps.
- `CSRF_TRUSTED_ORIGIN_REGEXES`, `CORS_ALLOWED_ORIGIN_REGEXES` e `AUTH_COOKIE_DOMAIN`: ajustam dominios publicos da instalacao.
- `SERVICE_PROXY_POSTGRES_HOST`, `SERVICE_PROXY_POSTGRES_PORT`, `SERVICE_PROXY_REDIS_HOST`, `SERVICE_PROXY_REDIS_PORT`, `SERVICE_PROXY_RABBITMQ_HOST` e `SERVICE_PROXY_RABBITMQ_PORT`: hosts e portas dos proxies de servicos, quando usados.
