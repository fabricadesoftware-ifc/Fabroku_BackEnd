from django.apps import AppConfig


class AppsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.apps'

    def ready(self):
        import core.apps.signals  # noqa: F401
