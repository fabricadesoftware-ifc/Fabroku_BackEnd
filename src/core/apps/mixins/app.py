from .apps.create_app import CreateAppMixin
from .apps.delete_app import DeleteAppMixin
from .apps.manage_app import ManageAppMixin
from .apps.redeploy_app import RedeployAppMixin
from .apps.run_command import RunCommandMixin
from .apps.update_app import UpdateAppMixin
from .services.create_service import CreateServiceMixin
from .services.delete_service import DeleteServiceMixin


class AppMixin(
    CreateAppMixin,
    DeleteAppMixin,
    RedeployAppMixin,
    UpdateAppMixin,
    ManageAppMixin,
    CreateServiceMixin,
    DeleteServiceMixin,
    RunCommandMixin,
):
    """Mixin agregador para operações de aplicações e serviços."""

    pass
