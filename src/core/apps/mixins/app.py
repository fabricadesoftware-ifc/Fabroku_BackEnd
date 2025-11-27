from core.apps.mixins import CreateAppMixin, DeleteAppMixin, UpdateAppMixin


class AppMixin(CreateAppMixin, DeleteAppMixin, UpdateAppMixin):
    """Mixin agregador para operações de aplicações."""
    pass
