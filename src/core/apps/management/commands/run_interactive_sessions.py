import logging
import threading
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from core.apps.interactive_runner import (
    build_default_runner_id,
    claim_pending_interactive_sessions,
    get_interactive_max_sessions,
    get_interactive_runner_heartbeat_seconds,
    touch_interactive_runner,
)
from core.apps.mixins.apps.interactive_run import execute_interactive_session

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Executa sessoes interativas do Fabroku fora do Celery.'

    def add_arguments(self, parser):
        parser.add_argument('--runner-id', default=None, help='Identificador estavel deste runner.')
        parser.add_argument(
            '--poll-interval',
            type=float,
            default=0.5,
            help='Intervalo de busca por sessoes pendentes.',
        )
        parser.add_argument('--once', action='store_true', help='Processa as sessoes disponiveis uma vez e encerra.')

    def handle(self, *args, **options):
        runner_id = options['runner_id'] or build_default_runner_id()
        max_sessions = get_interactive_max_sessions()
        poll_interval = max(0.1, float(options['poll_interval']))
        heartbeat_interval = get_interactive_runner_heartbeat_seconds()
        active_threads: dict[str, threading.Thread] = {}
        last_heartbeat_at = 0.0

        self.stdout.write(self.style.SUCCESS(f'Runner interativo iniciado: {runner_id}'))

        try:
            while True:
                active_threads = {
                    session_id: thread for session_id, thread in active_threads.items() if thread.is_alive()
                }

                now_monotonic = time.monotonic()
                if now_monotonic - last_heartbeat_at >= heartbeat_interval:
                    touch_interactive_runner(
                        runner_id,
                        active_sessions=len(active_threads),
                        max_sessions=max_sessions,
                    )
                    last_heartbeat_at = now_monotonic

                capacity = max_sessions - len(active_threads)
                if capacity > 0:
                    sessions = claim_pending_interactive_sessions(runner_id, limit=capacity)
                    for session in sessions:
                        session_id = str(session.id)
                        thread = threading.Thread(
                            target=self._run_session_thread,
                            args=(runner_id, session_id),
                            daemon=True,
                            name=f'interactive-{session_id}',
                        )
                        active_threads[session_id] = thread
                        thread.start()

                if options['once']:
                    for thread in active_threads.values():
                        thread.join()
                    touch_interactive_runner(
                        runner_id,
                        active_sessions=0,
                        max_sessions=max_sessions,
                    )
                    break

                time.sleep(poll_interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Runner interativo encerrado.'))
        finally:
            touch_interactive_runner(
                runner_id,
                active_sessions=0,
                max_sessions=max_sessions,
                metadata={'stopped': True},
            )

    @staticmethod
    def _run_session_thread(runner_id: str, session_id: str):
        close_old_connections()
        try:
            execute_interactive_session(
                session_id,
                runner_id=runner_id,
                task_id=f'interactive:{runner_id}:{session_id}',
            )
        except Exception:
            logger.exception('Sessao interativa falhou no runner dedicado.', extra={'session_id': session_id})
        finally:
            close_old_connections()
