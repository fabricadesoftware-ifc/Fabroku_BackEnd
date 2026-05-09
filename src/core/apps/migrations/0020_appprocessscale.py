import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0019_interactive_run_session_and_events'),
    ]

    operations = [
        migrations.CreateModel(
            name='AppProcessScale',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('process_name', models.CharField(max_length=64)),
                ('desired_quantity', models.PositiveSmallIntegerField(default=0)),
                ('current_quantity', models.PositiveSmallIntegerField(default=0)),
                ('detected_at', models.DateTimeField(auto_now_add=True)),
                ('last_synced_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'app',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='process_scales',
                        to='apps.app',
                    ),
                ),
            ],
            options={
                'verbose_name': 'App Process Scale',
                'verbose_name_plural': 'App Process Scales',
                'db_table': 'app_process_scales',
                'indexes': [models.Index(fields=['app', 'process_name'], name='idx_app_process_name')],
                'constraints': [
                    models.UniqueConstraint(fields=('app', 'process_name'), name='unique_app_process_scale'),
                ],
            },
        ),
    ]
