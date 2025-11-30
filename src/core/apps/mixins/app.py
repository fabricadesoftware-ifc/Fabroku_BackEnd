from .apps.create_app import CreateAppMixin
from .apps.delete_app import DeleteAppMixin
from .apps.update_app import UpdateAppMixin


class AppMixin(CreateAppMixin, DeleteAppMixin, UpdateAppMixin):
    """Mixin agregador para operações de aplicações."""

    pass
