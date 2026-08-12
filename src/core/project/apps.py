from django.apps import AppConfig


class ProjectConfig(AppConfig):
    """Shell app kept only for migration history (Fase 3).

    The `Project` model moved to `projects.models.Project` — see
    `migrations/0003_delete_project.py`. This app must stay registered in
    INSTALLED_APPS until that migration history is no longer needed
    (mirrors the plan's Fase 3.9 compatibility-shim window).
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.project'
