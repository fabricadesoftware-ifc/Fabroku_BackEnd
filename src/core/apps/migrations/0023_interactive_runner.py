import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0022_postgres_connect_audit'),
    ]

    operations = [
        migrations.AddField(
            model_name='interactiverunsession',
            name='claimed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='interactiverunsession',
            name='runner_id',
            field=models.CharField(blank=True, db_index=True, max_length=128, null=True),
        ),
        migrations.CreateModel(
            name='InteractiveRunRunner',
            fields=[
                ('runner_id', models.CharField(max_length=128, primary_key=True, serialize=False)),
                ('hostname', models.CharField(blank=True, default='', max_length=255)),
                ('pid', models.PositiveIntegerField(default=0)),
                ('max_sessions', models.PositiveIntegerField(default=1)),
                ('active_sessions', models.PositiveIntegerField(default=0)),
                ('started_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('last_heartbeat_at', models.DateTimeField(db_index=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
            ],
            options={
                'verbose_name': 'Interactive Run Runner',
                'verbose_name_plural': 'Interactive Run Runners',
                'db_table': 'interactive_run_runners',
            },
        ),
        migrations.AddIndex(
            model_name='interactiverunsession',
            index=models.Index(fields=['runner_id', 'status'], name='idx_irs_runner_status'),
        ),
        migrations.AddIndex(
            model_name='interactiverunrunner',
            index=models.Index(fields=['last_heartbeat_at'], name='idx_irr_last_heartbeat'),
        ),
    ]
