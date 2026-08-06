import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """State-only: registers User/CLIToken/AllowedEmail under `identity`, and
    (via AUTH_USER_MODEL = 'identity.User' in settings.py) makes `identity.User`
    the swappable user model.

    No database_operations — the `auth_user_user`/`auth_user_clitoken`/
    `auth_user_allowedemail` tables (and the `auth_user_user_groups`/
    `auth_user_user_user_permissions` M2M through-tables) already exist,
    created by core.auth_user's original migrations. db_table is set
    explicitly on every model below to freeze those exact names — unlike
    every other model moved in this refactor, User/CLIToken/AllowedEmail
    never had an explicit db_table before, so their physical table names
    were auto-derived from the OLD app_label ('auth_user'); this CreateModel
    reproduces that auto-derived name explicitly so the state migration to
    `identity` doesn't move to `identity_user` etc. Verified against
    `User._meta.db_table` / `.get_field('groups').m2m_db_table()` on the
    live app before writing this file.

    Every FK/M2M across the whole codebase that points at the user model uses
    `settings.AUTH_USER_MODEL` (a swappable dependency), never a hardcoded
    'auth_user.User' string — so nothing else needs an AlterField migration
    for this move; Django resolves those dynamically from the setting above.
    See core/auth_user/migrations/0008_... for the matching removal.
    """

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='AllowedEmail',
                    fields=[
                        (
                            'id',
                            models.BigAutoField(
                                auto_created=True, primary_key=True, serialize=False, verbose_name='ID'
                            ),
                        ),
                        (
                            'email',
                            models.EmailField(
                                db_index=True,
                                help_text='Email do professor/funcionário autorizado',
                                max_length=254,
                                unique=True,
                                verbose_name='E-mail',
                            ),
                        ),
                        (
                            'name',
                            models.CharField(
                                blank=True,
                                help_text='Nome do professor/funcionário (opcional)',
                                max_length=255,
                                null=True,
                                verbose_name='Nome',
                            ),
                        ),
                        (
                            'is_active',
                            models.BooleanField(
                                default=True,
                                help_text='Se desativado, o email não terá mais acesso',
                                verbose_name='Ativo',
                            ),
                        ),
                        (
                            'notes',
                            models.TextField(
                                blank=True,
                                help_text='Observações sobre este acesso',
                                null=True,
                                verbose_name='Observações',
                            ),
                        ),
                        ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                        ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
                    ],
                    options={
                        'verbose_name': 'Email Permitido',
                        'verbose_name_plural': 'Emails Permitidos',
                        'db_table': 'auth_user_allowedemail',
                        'ordering': ['email'],
                    },
                ),
                migrations.CreateModel(
                    name='User',
                    fields=[
                        (
                            'id',
                            models.BigAutoField(
                                auto_created=True, primary_key=True, serialize=False, verbose_name='ID'
                            ),
                        ),
                        ('password', models.CharField(max_length=128, verbose_name='password')),
                        ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                        (
                            'is_superuser',
                            models.BooleanField(
                                default=False,
                                help_text=(
                                    'Designates that this user has all permissions without '
                                    'explicitly assigning them.'
                                ),
                                verbose_name='superuser status',
                            ),
                        ),
                        ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
                        ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                        (
                            'is_staff',
                            models.BooleanField(
                                default=False,
                                help_text='Designates whether the user can log into this admin site.',
                                verbose_name='staff status',
                            ),
                        ),
                        (
                            'is_active',
                            models.BooleanField(
                                default=True,
                                help_text=(
                                    'Designates whether this user should be treated as active. '
                                    'Unselect this instead of deleting accounts.'
                                ),
                                verbose_name='active',
                            ),
                        ),
                        (
                            'date_joined',
                            models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined'),
                        ),
                        (
                            'email',
                            models.EmailField(
                                db_index=True, max_length=254, unique=True, verbose_name='e-mail address'
                            ),
                        ),
                        ('avatar_url', models.URLField(blank=True, max_length=500, null=True)),
                        ('name', models.CharField(db_index=True, max_length=255, null=True)),
                        (
                            'password_reset_token',
                            models.CharField(
                                blank=True, max_length=255, null=True, verbose_name='Password Reset Token'
                            ),
                        ),
                        (
                            'password_reset_token_created',
                            models.DateTimeField(
                                blank=True, null=True, verbose_name='Password Reset Token Created'
                            ),
                        ),
                        ('git_token', models.CharField(blank=True, max_length=255, null=True)),
                        (
                            'is_fabric',
                            models.BooleanField(
                                default=False,
                                help_text=(
                                    'Indica se o usuário é membro da Fábrica de Software. Membros podem '
                                    'personalizar nomes de apps.'
                                ),
                                verbose_name='membro da fábrica',
                            ),
                        ),
                        (
                            'custom_max_apps',
                            models.PositiveIntegerField(
                                blank=True,
                                help_text=(
                                    'Sobrescreve o limite padrão de apps para este usuário. Deixe vazio '
                                    'para usar o padrão do perfil.'
                                ),
                                null=True,
                                verbose_name='limite personalizado de apps',
                            ),
                        ),
                        (
                            'custom_max_services',
                            models.PositiveIntegerField(
                                blank=True,
                                help_text=(
                                    'Sobrescreve o limite padrão de serviços para este usuário. Deixe '
                                    'vazio para usar o padrão do perfil.'
                                ),
                                null=True,
                                verbose_name='limite personalizado de serviços',
                            ),
                        ),
                        (
                            'groups',
                            models.ManyToManyField(
                                blank=True,
                                help_text=(
                                    'The groups this user belongs to. A user will get all permissions '
                                    'granted to each of their groups.'
                                ),
                                related_name='user_set',
                                related_query_name='user',
                                to='auth.group',
                                verbose_name='groups',
                            ),
                        ),
                        (
                            'user_permissions',
                            models.ManyToManyField(
                                blank=True,
                                help_text='Specific permissions for this user.',
                                related_name='user_set',
                                related_query_name='user',
                                to='auth.permission',
                                verbose_name='user permissions',
                            ),
                        ),
                    ],
                    options={
                        'verbose_name': 'Usuário',
                        'verbose_name_plural': 'Usuários',
                        'db_table': 'auth_user_user',
                        'ordering': ['-date_joined'],
                    },
                ),
                migrations.CreateModel(
                    name='CLIToken',
                    fields=[
                        (
                            'id',
                            models.BigAutoField(
                                auto_created=True, primary_key=True, serialize=False, verbose_name='ID'
                            ),
                        ),
                        (
                            'token',
                            models.CharField(db_index=True, editable=False, max_length=64, unique=True),
                        ),
                        (
                            'name',
                            models.CharField(default='CLI', max_length=100, verbose_name='nome do dispositivo'),
                        ),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('last_used_at', models.DateTimeField(blank=True, null=True)),
                        ('is_active', models.BooleanField(default=True)),
                        (
                            'user',
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name='cli_tokens',
                                to=settings.AUTH_USER_MODEL,
                                verbose_name='usuário',
                            ),
                        ),
                    ],
                    options={
                        'verbose_name': 'Token CLI',
                        'verbose_name_plural': 'Tokens CLI',
                        'db_table': 'auth_user_clitoken',
                        'ordering': ['-created_at'],
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
