from django.apps import AppConfig


class DeployDjangoAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.deploy.infra.deploy_django_app'
