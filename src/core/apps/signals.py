from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from core.apps.models import App, Service
from core.auth_user.models import User
from core.cache_versioning import (
    APP_LAST_COMMIT_CACHE_NAMESPACE,
    ADMIN_STORAGE_USAGE_CACHE_NAMESPACE,
    ADMIN_USERS_LIST_CACHE_NAMESPACE,
    bump_cache_version,
)
from core.project.models import Project


def _invalidate_admin_users_cache():
    bump_cache_version(ADMIN_USERS_LIST_CACHE_NAMESPACE)


def _invalidate_storage_usage_cache():
    bump_cache_version(ADMIN_STORAGE_USAGE_CACHE_NAMESPACE)


def _invalidate_last_commit_cache():
    bump_cache_version(APP_LAST_COMMIT_CACHE_NAMESPACE)


@receiver(post_save, sender=User)
@receiver(post_delete, sender=User)
def invalidate_admin_users_cache_for_user_change(sender, **kwargs):
    _invalidate_admin_users_cache()
    _invalidate_last_commit_cache()


@receiver(post_save, sender=Project)
@receiver(post_delete, sender=Project)
def invalidate_project_dependent_caches(sender, **kwargs):
    _invalidate_admin_users_cache()
    _invalidate_storage_usage_cache()
    _invalidate_last_commit_cache()


@receiver(m2m_changed, sender=Project.users.through)
def invalidate_admin_users_cache_for_project_membership(sender, **kwargs):
    _invalidate_admin_users_cache()
    _invalidate_last_commit_cache()


@receiver(post_save, sender=App)
@receiver(post_delete, sender=App)
def invalidate_app_dependent_caches(sender, **kwargs):
    _invalidate_admin_users_cache()
    _invalidate_storage_usage_cache()
    _invalidate_last_commit_cache()


@receiver(post_save, sender=Service)
@receiver(post_delete, sender=Service)
def invalidate_service_dependent_caches(sender, **kwargs):
    _invalidate_admin_users_cache()
    _invalidate_storage_usage_cache()
