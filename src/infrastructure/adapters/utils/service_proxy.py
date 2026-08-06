from django.conf import settings

from service_mgmt.models import Service, ServiceType
from service_mgmt.service_types import is_postgres_service_type


class ServiceProxyMixin:
    """Mixin para manipulacao de proxies de servicos."""

    def get_service_proxy_url(self, service: Service) -> str:
        """Retorna a URL de proxy do servico."""
        if is_postgres_service_type(service.service_type):
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
