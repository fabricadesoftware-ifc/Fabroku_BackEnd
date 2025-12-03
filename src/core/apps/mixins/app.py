from .apps.create_app import CreateAppMixin
from .apps.delete_app import DeleteAppMixin
from .apps.redeploy_app import RedeployAppMixin
from .apps.update_app import UpdateAppMixin


class AppMixin(CreateAppMixin, DeleteAppMixin, RedeployAppMixin, UpdateAppMixin):
    """Mixin agregador para operações de aplicações."""

    pass
