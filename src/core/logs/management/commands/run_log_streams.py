import signal

from django.core.management.base import BaseCommand

from core.logs.logstream import LogStreamSupervisor


class Command(BaseCommand):
    help = 'Executa o runner dedicado de streaming de logs runtime.'

    def handle(self, *args, **options):
        supervisor = LogStreamSupervisor()

        def stop(_signum, _frame):
            self.stdout.write(self.style.WARNING('Encerrando runner de logstream...'))
            supervisor.stop()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        self.stdout.write(self.style.SUCCESS(f'Runner de logstream iniciado: {supervisor.runner_id}'))
        supervisor.run_forever()
