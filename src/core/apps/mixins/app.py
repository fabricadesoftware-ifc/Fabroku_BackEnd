from .apps.interactive_run import InteractiveRunMixin


class AppMixin(InteractiveRunMixin):
    """Mixin agregador para operacoes de aplicacoes.

    Create/delete/redeploy/update/manage/run_command/run_data/process_scale ja
    foram portados para use cases (applications/use_cases/, applications/tasks.py)
    e removidos daqui. A sessao interativa (loop de execucao SSH) ainda nao tem
    use case equivalente — ver ADJUSTS_REFACTOR.md, Fase E.
    """

    pass
