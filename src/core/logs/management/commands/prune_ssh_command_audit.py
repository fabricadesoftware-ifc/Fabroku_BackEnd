from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.logs.models import SSHCommandAudit


class Command(BaseCommand):
    help = 'Remove auditorias SSH antigas conforme SSH_AUDIT_RETENTION_DAYS.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=None)

    def handle(self, *args, **options):
        days = options['days'] or int(settings.SSH_AUDIT_RETENTION_DAYS)
        cutoff = timezone.now() - timedelta(days=max(1, days))
        deleted_count, _ = SSHCommandAudit.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f'Auditorias SSH removidas: {deleted_count}'))
