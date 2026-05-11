import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0021_soft_delete_apps_services'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='interactiverunsession',
            name='audit_sequence',
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='interactiverunsession',
            name='client_ip',
            field=models.CharField(blank=True, max_length=45, null=True),
        ),
        migrations.AddField(
            model_name='interactiverunsession',
            name='service',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='interactive_sessions',
                to='apps.service',
            ),
        ),
        migrations.AddField(
            model_name='interactiverunsession',
            name='user_agent',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='interactiverunsession',
            name='command_kind',
            field=models.CharField(
                choices=[
                    ('django_createsuperuser', 'Django Createsuperuser'),
                    ('postgres_connect', 'Postgres Connect'),
                ],
                max_length=64,
            ),
        ),
        migrations.CreateModel(
            name='InteractiveRunAuditChunk',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                (
                    'direction',
                    models.CharField(choices=[('input', 'Input'), ('output', 'Output')], max_length=12),
                ),
                ('sequence', models.PositiveBigIntegerField()),
                ('size', models.PositiveIntegerField(default=0)),
                ('content_ciphertext', models.BinaryField()),
                ('consumed_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    'session',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='audit_chunks',
                        to='apps.interactiverunsession',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Interactive Run Audit Chunk',
                'verbose_name_plural': 'Interactive Run Audit Chunks',
                'db_table': 'interactive_run_audit_chunks',
            },
        ),
        migrations.AddIndex(
            model_name='interactiverunsession',
            index=models.Index(fields=['service', 'created_at'], name='idx_irs_service_created'),
        ),
        migrations.AddConstraint(
            model_name='interactiverunauditchunk',
            constraint=models.UniqueConstraint(fields=['session', 'sequence'], name='unique_ira_session_sequence'),
        ),
        migrations.AddIndex(
            model_name='interactiverunauditchunk',
            index=models.Index(fields=['session', 'sequence'], name='idx_ira_session_seq'),
        ),
        migrations.AddIndex(
            model_name='interactiverunauditchunk',
            index=models.Index(fields=['session', 'direction', 'sequence'], name='idx_ira_session_dir_seq'),
        ),
        migrations.AddIndex(
            model_name='interactiverunauditchunk',
            index=models.Index(fields=['direction', 'consumed_at'], name='idx_ira_dir_consumed'),
        ),
    ]
