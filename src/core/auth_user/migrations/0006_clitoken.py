import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('auth_user', '0005_add_is_fabric'),
    ]

    operations = [
        migrations.CreateModel(
            name='CLIToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(db_index=True, editable=False, max_length=64, unique=True)),
                ('name', models.CharField(default='CLI', max_length=100, verbose_name='nome do dispositivo')),
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
                'ordering': ['-created_at'],
            },
        ),
    ]
