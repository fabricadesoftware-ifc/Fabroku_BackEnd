from django.core.management.base import BaseCommand, CommandError

from applications.models import App
from infrastructure.adapters.dokku import DokkuAdapter
from service_mgmt.models import Service

HEADER_TOKENS = {'NAME', 'NAME:'}
LIST_FAILURE_PREFIXES = ('failed to execute command:', 'ssh connection error:', 'ssh command timeout')


def parse_dokku_list(output: str) -> list[str]:
    """Primeira coluna de `apps:list`/`postgres:list`/`redis:list`, sem cabecalhos do Dokku."""
    names = []
    for raw_line in (output or '').splitlines():
        line = raw_line.strip()
        if not line or line.startswith(('=====>', '!', '-----')):
            continue
        token = line.split()[0]
        if token not in HEADER_TOKENS:
            names.append(token)
    return names


def last_deleted(queryset, field: str, name: str):
    return queryset.filter(**{field: name}).exclude(deleted_at=None).order_by('-deleted_at').first()


class Command(BaseCommand):
    help = 'Lista apps/servicos que existem no Dokku sem registro ativo no Fabroku (somente leitura).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--exclude', nargs='*', default=[], help='Nomes do Dokku a ignorar (ex: os apps do proprio Fabroku).'
        )

    def handle(self, *args, **options):
        dokku = DokkuAdapter()
        exclude = set(options['exclude'])

        sources = [
            ('app', dokku.get_apps(), App.objects, 'name_dokku'),
            ('postgres', dokku.get_databases(), Service.objects, 'container_name'),
            ('redis', dokku.list_redis(), Service.objects, 'container_name'),
        ]

        total = 0
        for kind, output, queryset, field in sources:
            if output.lower().startswith(LIST_FAILURE_PREFIXES):
                raise CommandError(f'Falha ao listar {kind} no Dokku: {output}')

            active = set(queryset.filter(deleted_at=None).values_list(field, flat=True))
            if queryset.model is Service:
                # Services antigos sem container_name usam o name como nome no Dokku.
                active |= set(queryset.filter(deleted_at=None).values_list('name', flat=True))
            orphans = [n for n in parse_dokku_list(output) if n not in active and n not in exclude]
            for name in orphans:
                record = last_deleted(queryset, field, name)
                if record:
                    by = record.deleted_by.email if record.deleted_by else '?'
                    note = f'soft delete em {record.deleted_at:%Y-%m-%d %H:%M} por {by} (id {record.id})'
                else:
                    note = 'sem registro no banco (cascade antigo ou criado fora do Fabroku)'
                self.stdout.write(f'{kind:<9} {name:<40} {note}')
            total += len(orphans)

        self.stdout.write(self.style.SUCCESS(f'\nTotal de orfaos: {total}'))
