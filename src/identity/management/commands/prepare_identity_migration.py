from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder


TARGET_MIGRATION = ("identity", "0001_initial")
ADMIN_MIGRATION = ("admin", "0001_initial")

REQUIRED_TABLES = {
    "auth_user_user",
    "auth_user_clitoken",
    "auth_user_allowedemail",
    "auth_user_user_groups",
    "auth_user_user_user_permissions",
}


class Command(BaseCommand):
    help = (
        "Registra identity.0001_initial em bancos legados que já possuem "
        "as tabelas físicas auth_user_*."
    )

    def handle(self, *args, **options):
        recorder = MigrationRecorder(connection)
        applied = recorder.applied_migrations()

        # Já foi corrigido anteriormente.
        if TARGET_MIGRATION in applied:
            self.stdout.write(
                self.style.SUCCESS(
                    "identity.0001_initial já está registrada."
                )
            )
            return

        # Banco novo: não existe histórico antigo para compatibilizar.
        # O migrate normal deve cuidar dele.
        if ADMIN_MIGRATION not in applied:
            self.stdout.write(
                "Banco ainda não possui admin.0001_initial; "
                "nenhuma compatibilização foi necessária."
            )
            return

        user_model = get_user_model()

        if user_model._meta.label != "identity.User":
            raise CommandError(
                "AUTH_USER_MODEL inesperado: "
                f"{user_model._meta.label}. Esperado: identity.User."
            )

        if user_model._meta.db_table != "auth_user_user":
            raise CommandError(
                "Tabela configurada para identity.User é "
                f"{user_model._meta.db_table!r}, mas deveria ser "
                "'auth_user_user'."
            )

        existing_tables = set(connection.introspection.table_names())
        missing_tables = REQUIRED_TABLES - existing_tables

        if missing_tables:
            formatted = ", ".join(sorted(missing_tables))
            raise CommandError(
                "Não é seguro registrar identity.0001_initial. "
                f"Tabelas ausentes: {formatted}"
            )

        old_auth_migrations = {
            name
            for app, name in applied
            if app == "auth_user"
        }

        if not old_auth_migrations:
            raise CommandError(
                "Nenhuma migração antiga do app auth_user foi encontrada. "
                "A correção automática foi interrompida."
            )

        with transaction.atomic(using=connection.alias):
            # Verifica novamente dentro da transação.
            applied = recorder.applied_migrations()

            if TARGET_MIGRATION not in applied:
                recorder.record_applied(*TARGET_MIGRATION)

        self.stdout.write(
            self.style.SUCCESS(
                "identity.0001_initial registrada com segurança."
            )
        )