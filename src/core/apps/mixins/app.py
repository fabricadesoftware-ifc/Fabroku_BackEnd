from .apps.create_app import CreateAppMixin
from .apps.delete_app import DeleteAppMixin
from .apps.interactive_run import InteractiveRunMixin
from .apps.manage_app import ManageAppMixin
from .apps.redeploy_app import RedeployAppMixin
from .apps.run_command import RunCommandMixin
from .apps.run_data import RunDataMixin
from .apps.update_app import UpdateAppMixin


class AppMixin(
    CreateAppMixin,
    DeleteAppMixin,
    RedeployAppMixin,
    UpdateAppMixin,
    ManageAppMixin,
    RunCommandMixin,
    RunDataMixin,
    InteractiveRunMixin,
):
    """Mixin agregador para operacoes de aplicacoes."""

    pass
