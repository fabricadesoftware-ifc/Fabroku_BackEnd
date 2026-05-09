from .services.create_service import CreateServiceMixin
from .services.create_service_standalone import CreateServiceStandaloneMixin
from .services.delete_service import DeleteServiceMixin
from .services.link_service import LinkServiceMixin
from .services.unlink_service import UnlinkServiceMixin


class ServiceMixin(
    CreateServiceMixin,
    CreateServiceStandaloneMixin,
    DeleteServiceMixin,
    LinkServiceMixin,
    UnlinkServiceMixin,
):
    """Mixin agregador para operacoes de servicos."""

    pass
