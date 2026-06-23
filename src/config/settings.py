"""
Django settings para o projeto Fabroku.

Gerado por Django e customizado para integração com Dokku.
Para mais informações: https://docs.djangoproject.com/en/5.2/topics/settings/
"""

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()


def _parse_csv_env(name, default=None):
    raw_value = os.getenv(name)
    if raw_value is None:
        return list(default or [])
    return [item.strip() for item in raw_value.split(',') if item.strip()]


def _parse_bool_env(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _optional_env(name, default=None):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip() or None


LOCAL_DEV_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:5173',
    'http://127.0.0.1:5173',
]

DEFAULT_TRUSTED_ORIGINS = [
    *LOCAL_DEV_ORIGINS,
    'https://fabroku.fabricadesoftware.ifc.edu.br',
    'https://fabroku-api.fabricadesoftware.ifc.edu.br',
    'https://*.fabricadesoftware.ifc.edu.br',
    'https://*.fexcompany.me',
]


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY')

CELERY_BROKER_URL = os.getenv('BROKER_URL', 'amqp://paineluser:senha123@172.21.238.11:5672/painel')

BROKER_URL = CELERY_BROKER_URL


DEBUG = os.getenv('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*').split(',')
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = _parse_bool_env('USE_X_FORWARDED_HOST', True)

ROOT_URLCONF = 'config.urls'

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'drf_spectacular',
    'django_filters',
    'channels',
    'django_celery_results',
    'core.adapters',
    'core.logs',
    'core.project',
    'core.apps',
    'core.auth_user',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.logs.middleware.SSHCommandAuditContextMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

DATABASES = {'default': dj_database_url.config(default=f'sqlite:///{BASE_DIR / "db.sqlite3"}')}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'pt-br'

TIME_ZONE = 'America/Sao_Paulo'

USE_I18N = True

USE_TZ = True

STATIC_URL = 'static/'

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

CSRF_TRUSTED_ORIGINS = _parse_csv_env('CSRF_TRUSTED_ORIGINS', DEFAULT_TRUSTED_ORIGINS)


CORS_ALLOWED_ORIGINS = _parse_csv_env('CORS_ALLOWED_ORIGINS', LOCAL_DEV_ORIGINS + [
    'https://fabroku.fabricadesoftware.ifc.edu.br',
    'https://fabroku-api.fabricadesoftware.ifc.edu.br',
])

CORS_ALLOWED_ORIGIN_REGEXES = _parse_csv_env('CORS_ALLOWED_ORIGIN_REGEXES', [
    r'^https://.*\.fabricadesoftware\.ifc\.edu\.br$',
    r'^https://.*\.fexcompany\.me$',
])

AUTH_COOKIE_DOMAIN = _optional_env('AUTH_COOKIE_DOMAIN', '.fabricadesoftware.ifc.edu.br')
AUTH_COOKIE_SAMESITE = 'None'
AUTH_COOKIE_SECURE = True

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'core.auth_user.authentication.CookieJWTAuthentication',  # Cookie auth (prioridade)
        'rest_framework_simplejwt.authentication.JWTAuthentication',  # Header auth (fallback)
        'core.auth_user.authentication.CLITokenAuthentication',  # CLI token auth
    ),
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
        'rest_framework.renderers.AdminRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.FormParser',
        'rest_framework.parsers.MultiPartParser',
    ],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
}

# Configurações de Cookies para autenticação
AUTH_COOKIE_NAME = 'access_token'
AUTH_COOKIE_HTTP_ONLY = True
AUTH_COOKIE_PATH = '/'
AUTH_COOKIE_REFRESH_NAME = 'refresh_token'


SPECTACULAR_SETTINGS = {
    'TITLE': 'Fabroku API',
    'DESCRIPTION': 'API para gerenciamento do Fabroku, incluindo endpoints e documentação.',
    'VERSION': '1.0.0',
}

AUTH_USER_MODEL = 'auth_user.User'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

GITHUB_CLIENT_ID = os.getenv('GITHUB_CLIENT_ID')
GITHUB_CLIENT_SECRET = os.getenv('GITHUB_CLIENT_SECRET')
GITHUB_WEBHOOK_SECRET = os.getenv('GITHUB_WEBHOOK_SECRET')  # Opcional: para validar assinatura dos webhooks

DOKKU_SSH_KEY = os.getenv('DOKKU_SSH_KEY')
DOKKU_SSH_USERNAME = os.getenv('DOKKU_SSH_USERNAME', 'dokku')
DOKKU_SSH_HOST = os.getenv('DOKKU_SSH_HOST', '127.0.0.1')
DOKKU_SSH_PORT = int(os.getenv('DOKKU_SSH_PORT', 22))  # noqa: PLW1508
GITHUB_REDIRECT_URI = os.getenv('GITHUB_REDIRECT_URI', 'http://localhost:8000/api/auth/github/callback')
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:3000')  # noqa: PLW1508
BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:8000')  # URL pública do backend para webhooks
AUTH_ALLOWED_EMAIL_DOMAINS = _parse_csv_env('AUTH_ALLOWED_EMAIL_DOMAINS', ['estudantes.ifc.edu.br'])
AUTH_ALLOW_ALL_VERIFIED_EMAILS = _parse_bool_env('AUTH_ALLOW_ALL_VERIFIED_EMAILS', False)
AUTH_EMAIL_REJECTION_MESSAGE = os.getenv('AUTH_EMAIL_REJECTION_MESSAGE', 'O email do usuário não é do IFC.')
FABROKU_ORGANIZATION_NAME = os.getenv('FABROKU_ORGANIZATION_NAME', 'Fábrica de Software')
FABROKU_PRIVILEGED_ROLE_LABEL = os.getenv('FABROKU_PRIVILEGED_ROLE_LABEL', 'Membro da Fábrica')
FABROKU_REGULAR_ROLE_LABEL = os.getenv('FABROKU_REGULAR_ROLE_LABEL', 'Aluno')
FABROKU_APP_DOMAIN_SUFFIX = os.getenv('FABROKU_APP_DOMAIN_SUFFIX', '.class.fabricadesoftware.ifc.edu.br')
SERVICE_PROXY_POSTGRES_HOST = os.getenv(
    'SERVICE_PROXY_POSTGRES_HOST',
    'proxy.pg.coolify.fabricadesoftware.ifc.edu.br',
)
SERVICE_PROXY_POSTGRES_PORT = int(os.getenv('SERVICE_PROXY_POSTGRES_PORT', 1022))  # noqa: PLW1508
SERVICE_PROXY_REDIS_HOST = os.getenv('SERVICE_PROXY_REDIS_HOST', 'proxy.redis.coolify.fabricadesoftware.ifc.edu.br')
SERVICE_PROXY_REDIS_PORT = int(os.getenv('SERVICE_PROXY_REDIS_PORT', 6379))  # noqa: PLW1508
SERVICE_PROXY_RABBITMQ_HOST = os.getenv(
    'SERVICE_PROXY_RABBITMQ_HOST',
    'proxy.rabbitmq.coolify.fabricadesoftware.ifc.edu.br',
)
SERVICE_PROXY_RABBITMQ_PORT = int(os.getenv('SERVICE_PROXY_RABBITMQ_PORT', 5672))  # noqa: PLW1508
CACHE_TTL_DEFAULT = int(os.getenv('CACHE_TTL_DEFAULT', 60))
# Caches especificos podem sobrescrever esse valor com env vars no formato CACHE_TTL_<NAMESPACE>.
ADMIN_STORAGE_USAGE_MAX_WORKERS = int(os.getenv('ADMIN_STORAGE_USAGE_MAX_WORKERS', 6))
CLI_RUN_ARTIFACT_MAX_BYTES = int(os.getenv('CLI_RUN_ARTIFACT_MAX_BYTES', 50 * 1024 * 1024))
CLI_INTERACTIVE_SESSION_IDLE_SECONDS = int(os.getenv('CLI_INTERACTIVE_SESSION_IDLE_SECONDS', 5 * 60))
APP_PROCESS_MAX_INSTANCES = int(os.getenv('APP_PROCESS_MAX_INSTANCES', 5))
CHANNEL_REDIS_URL = os.getenv('CHANNEL_REDIS_URL', os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0'))
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [CHANNEL_REDIS_URL],
        },
    },
}
CLI_INTERACTIVE_MAX_SESSIONS = int(os.getenv('CLI_INTERACTIVE_MAX_SESSIONS', 20))
CLI_INTERACTIVE_RUNNER_HEARTBEAT_SECONDS = int(os.getenv('CLI_INTERACTIVE_RUNNER_HEARTBEAT_SECONDS', 10))
CLI_INTERACTIVE_ENABLE_CHANNEL_LAYER_EVENTS = _parse_bool_env('CLI_INTERACTIVE_ENABLE_CHANNEL_LAYER_EVENTS', False)
LOG_STREAM_BUFFER_LINES = int(os.getenv('LOG_STREAM_BUFFER_LINES', '500'))
LOG_STREAM_IDLE_SECONDS = int(os.getenv('LOG_STREAM_IDLE_SECONDS', '30'))
LOG_STREAM_RUNNER_HEARTBEAT_SECONDS = int(os.getenv('LOG_STREAM_RUNNER_HEARTBEAT_SECONDS', '10'))
SSH_AUDIT_ENABLED = _parse_bool_env('SSH_AUDIT_ENABLED', True)
SSH_AUDIT_RETENTION_DAYS = int(os.getenv('SSH_AUDIT_RETENTION_DAYS', '7'))

CELERY_TIMEZONE = 'America/Sao_Paulo'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_RESULT_BACKEND = 'django-db'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
