import re

from django.conf import settings
from django.utils import timezone

from core.apps.models import App, AppProcessScale

IGNORED_PROCESS_NAMES = {'release'}
PROCESS_NAME_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
PROCESS_SCALE_LINE_PATTERN = re.compile(r'^\s*([A-Za-z0-9][A-Za-z0-9_-]*)\s*:\s*(\d+)\s*$')
ANSI_PATTERN = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def get_process_max_instances() -> int:
    return max(1, int(getattr(settings, 'APP_PROCESS_MAX_INSTANCES', 5)))


def is_manageable_process_name(process_name: str) -> bool:
    normalized = (process_name or '').strip()
    return bool(PROCESS_NAME_PATTERN.match(normalized)) and normalized.lower() not in IGNORED_PROCESS_NAMES


def parse_ps_scale_output(output: str) -> dict[str, int]:
    """Extrai processos gerenciaveis da tabela de `dokku ps:scale`."""
    processes: dict[str, int] = {}
    clean_output = ANSI_PATTERN.sub('', output or '')

    for raw_line in clean_output.splitlines():
        line = raw_line.strip()
        match = PROCESS_SCALE_LINE_PATTERN.match(line)
        if not match:
            continue

        process_name, quantity = match.groups()
        if not is_manageable_process_name(process_name):
            continue

        processes[process_name] = int(quantity)

    return processes


def dokku_scale_output_failed(output: str) -> bool:
    output_lower = (output or '').lower()
    return 'failed' in output_lower or 'ssh connection error' in output_lower


def validate_process_quantities(processes: dict) -> dict[str, int]:
    if not isinstance(processes, dict) or not processes:
        raise ValueError('Informe pelo menos um processo para escalar.')

    max_instances = get_process_max_instances()
    validated: dict[str, int] = {}

    for raw_name, raw_quantity in processes.items():
        process_name = str(raw_name).strip()
        if not is_manageable_process_name(process_name):
            raise ValueError(f'Processo nao gerenciavel: {process_name or "(vazio)"}')

        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Quantidade invalida para {process_name}.') from exc

        if quantity < 0 or quantity > max_instances:
            raise ValueError(f'{process_name} deve ficar entre 0 e {max_instances} instancias.')

        if process_name.lower() == 'web' and quantity == 0:
            raise ValueError('Nao e permitido definir web=0 por esta tela. Use o botao Parar para parar o app.')

        validated[process_name] = quantity

    return validated


def sync_app_process_scales_from_dokku(app: App, dokku_adapter, *, output: str | None = None) -> list[AppProcessScale]:
    if not app.name_dokku:
        raise RuntimeError('App nao tem name_dokku configurado.')

    scale_output = output if output is not None else dokku_adapter.ps_scale_report(app.name_dokku)
    if dokku_scale_output_failed(scale_output):
        raise RuntimeError(scale_output)

    parsed_processes = parse_ps_scale_output(scale_output)
    synced_at = timezone.now()
    process_scales: list[AppProcessScale] = []

    for process_name, current_quantity in parsed_processes.items():
        process_scale, created = AppProcessScale.objects.get_or_create(
            app=app,
            process_name=process_name,
            defaults={
                'desired_quantity': current_quantity,
                'current_quantity': current_quantity,
                'last_synced_at': synced_at,
            },
        )

        if not created:
            process_scale.current_quantity = current_quantity
            process_scale.last_synced_at = synced_at
            process_scale.save(update_fields=['current_quantity', 'last_synced_at', 'updated_at'])

        process_scales.append(process_scale)

    return process_scales


def get_saved_process_quantities(app: App, *, process_names: set[str] | None = None) -> dict[str, int]:
    queryset = AppProcessScale.objects.filter(app=app)
    if process_names is not None:
        queryset = queryset.filter(process_name__in=process_names)

    return {
        process_scale.process_name: process_scale.desired_quantity
        for process_scale in queryset
        if is_manageable_process_name(process_scale.process_name)
    }


def save_desired_process_quantities(app: App, processes: dict[str, int]) -> None:
    synced_at = timezone.now()

    for process_name, quantity in processes.items():
        AppProcessScale.objects.update_or_create(
            app=app,
            process_name=process_name,
            defaults={
                'desired_quantity': quantity,
                'current_quantity': quantity,
                'last_synced_at': synced_at,
            },
        )


def reapply_saved_process_scales(app: App, dokku_adapter, logger=None, *, progress: int = 92) -> dict[str, int]:
    existing_saved_processes = get_saved_process_quantities(app)
    detected_scales = sync_app_process_scales_from_dokku(app, dokku_adapter)
    current_quantities = {
        process_scale.process_name: process_scale.current_quantity
        for process_scale in detected_scales
    }
    saved_processes = {
        process_name: quantity
        for process_name, quantity in existing_saved_processes.items()
        if process_name in current_quantities and quantity != current_quantities[process_name]
    }

    if not saved_processes:
        return {}

    output = dokku_adapter.ps_scale(app.name_dokku, saved_processes)
    if logger:
        logger.dokku(
            output,
            command=f'dokku ps:scale {app.name_dokku} '
            + ' '.join(f'{name}={quantity}' for name, quantity in saved_processes.items()),
            progress=progress,
        )

    if dokku_scale_output_failed(output):
        raise RuntimeError(output)

    save_desired_process_quantities(app, saved_processes)
    sync_app_process_scales_from_dokku(app, dokku_adapter, output=output)
    return saved_processes
