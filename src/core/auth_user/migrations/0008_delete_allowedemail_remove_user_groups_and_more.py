from django.db import migrations


class Migration(migrations.Migration):
    """State-only: removes AllowedEmail/User/CLIToken from core.auth_user's
    state — they now live in `identity` (see identity/migrations/0001_initial.py).

    No database_operations — none of these tables (or the groups/user_permissions
    M2M through-tables) are touched. Depends on identity's 0001 out of caution/
    consistency with every other model move in this refactor, even though
    Django's autodetector didn't require it here: every FK/M2M to the user model
    resolves dynamically via settings.AUTH_USER_MODEL (swappable), not a
    hardcoded 'auth_user.User' string, so there's no other app whose state
    still points at this model by the time this migration runs.
    """

    dependencies = [
        ('auth_user', '0007_user_custom_max_apps_user_custom_max_services'),
        ('identity', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name='AllowedEmail',
                ),
                migrations.RemoveField(
                    model_name='user',
                    name='groups',
                ),
                migrations.RemoveField(
                    model_name='user',
                    name='user_permissions',
                ),
                migrations.DeleteModel(
                    name='CLIToken',
                ),
                migrations.DeleteModel(
                    name='User',
                ),
            ],
            database_operations=[],
        ),
    ]
