from django.conf import settings

from core.apps.models import Service, ServiceType


class ServiceProxyMixin:
    """Mixin para manipulacao de proxies de servicos."""

    def get_service_proxy_url(self, service: Service) -> str:
        """Retorna a URL de proxy do servico."""
        if service.service_type == ServiceType.POSTGRES:
            return (
                f'postgres://{service.user}:{service.password}@'
                f'{settings.SERVICE_PROXY_POSTGRES_HOST}:{settings.SERVICE_PROXY_POSTGRES_PORT}/{service.name}'
            )
        if service.service_type == ServiceType.REDIS:
            return (
                f'redis://{service.user}:{service.password}@'
                f'{settings.SERVICE_PROXY_REDIS_HOST}:{settings.SERVICE_PROXY_REDIS_PORT}/{service.name}'
            )
        if service.service_type == ServiceType.RABBITMQ:
            return (
                f'amqp://{service.user}:{service.password}@'
                f'{settings.SERVICE_PROXY_RABBITMQ_HOST}:{settings.SERVICE_PROXY_RABBITMQ_PORT}/{service.name}'
            )

        raise ValueError('Tipo de servico desconhecido')
