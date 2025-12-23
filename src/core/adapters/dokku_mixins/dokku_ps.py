from abc import abstractmethod


class DokkuPsMixin:
    """Mixin para gerenciar processos (ps) de aplicações no Dokku."""

    @abstractmethod
    def _run_command(self, command: str) -> str:
        """Executa um comando no servidor Dokku."""
        ...

    def ps_inspect(self, app_name: str) -> str:
        """
        Exibe uma versão sanitizada do docker inspect da aplicação.
        dokku ps:inspect <app>
        """
        return self._run_command(f'ps:inspect {app_name}')

    def ps_report(self, app_name: str | None = None, flag: str | None = None) -> str:
        """
        Exibe o relatório de processos.
        dokku ps:report [<app>] [<flag>]
        """
        command = 'ps:report'
        if app_name:
            command += f' {app_name}'
        if flag:
            command += f' {flag}'
        return self._run_command(command)

    def ps_restart(
        self,
        app_name: str,
        process_name: str | None = None,
        parallel: int | None = None,
        all_apps: bool = False,
    ) -> str:
        """
        Reinicia processos de uma aplicação.
        dokku ps:restart [--parallel count] [--all|<app>] [<process-name>]
        """
        command = 'ps:restart'

        if parallel is not None:
            command += f' --parallel {parallel}'

        if all_apps:
            command += ' --all'
        else:
            command += f' {app_name}'

        if process_name:
            command += f' {process_name}'

        return self._run_command(command)

    def ps_scale(self, app_name: str, processes: dict[str, int], skip_deploy: bool = False) -> str:
        """
        Define a quantidade de instâncias de processos.
        dokku ps:scale [--skip-deploy] <app> <proc>=<count> ...
        """
        proc_args = ' '.join(f'{proc}={count}' for proc, count in processes.items())

        command = 'ps:scale'
        if skip_deploy:
            command += ' --skip-deploy'

        command += f' {app_name} {proc_args}'
        return self._run_command(command)

    def ps_set(self, app_name: str, key: str, value: str | None = None) -> str:
        """
        Define ou limpa uma propriedade de ps.
        dokku ps:set <app> <key> <value>
        """
        if value is None:
            return self._run_command(f'ps:set {app_name} {key}')
        return self._run_command(f'ps:set {app_name} {key} {value}')

    def ps_start(
        self,
        app_name: str | None = None,
        parallel: int | None = None,
        all_apps: bool = False,
    ) -> str:
        """
        Inicia processos.
        dokku ps:start [--parallel count] [--all|<app>]
        """
        command = 'ps:start'

        if parallel is not None:
            command += f' --parallel {parallel}'

        if all_apps:
            command += ' --all'
        elif app_name:
            command += f' {app_name}'

        return self._run_command(command)

    def ps_stop(
        self,
        app_name: str | None = None,
        parallel: int | None = None,
        all_apps: bool = False,
    ) -> str:
        """
        Para processos.
        dokku ps:stop [--parallel count] [--all|<app>]
        """
        command = 'ps:stop'

        if parallel is not None:
            command += f' --parallel {parallel}'

        if all_apps:
            command += ' --all'
        elif app_name:
            command += f' {app_name}'

        return self._run_command(command)

    def ps_rebuild(
        self,
        app_name: str | None = None,
        parallel: int | None = None,
        all_apps: bool = False,
    ) -> str:
        """
        Rebuilda uma aplicação a partir do código fonte.
        dokku ps:rebuild [--parallel count] [--all|<app>]
        """
        command = 'ps:rebuild'

        if parallel is not None:
            command += f' --parallel {parallel}'

        if all_apps:
            command += ' --all'
        elif app_name:
            command += f' {app_name}'

        return self._run_command(command)

    def ps_restore(self, app_name: str) -> str:
        """
        Restaura aplicações que estavam rodando (ex: após reboot).
        dokku ps:restore <app>
        """
        return self._run_command(f'ps:restore {app_name}')
