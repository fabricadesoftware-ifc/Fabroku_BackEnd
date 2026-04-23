# postgres://{uuid}:{password}@proxy.pg.coolify.fabricadesoftware.ifc.edu.br:1022/{database}
from core.apps.models import Service, ServiceType


class ServiceProxyMixin:
    """Mixin para manipulação de proxies de serviços."""

    def get_service_proxy_url(self, service: Service) -> str:
        """Retorna a URL de proxy do serviço."""
        if service.service_type == ServiceType.POSTGRES:
            return f"postgres://{service.user}:{service.password}@proxy.pg.coolify.fabricadesoftware.ifc.edu.br:1022/{service.name}"
        elif service.service_type == ServiceType.REDIS:
            return f"redis://{service.user}:{service.password}@proxy.redis.coolify.fabricadesoftware.ifc.edu.br:6379/{service.name}"
        elif service.service_type == ServiceType.RABBITMQ:
            return f"amqp://{service.user}:{service.password}@proxy.rabbitmq.coolify.fabricadesoftware.ifc.edu.br:5672/{service.name}"
        else:
            raise ValueError("Tipo de serviço desconhecido")
