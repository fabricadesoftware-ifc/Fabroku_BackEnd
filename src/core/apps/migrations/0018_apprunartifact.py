import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0017_cacheversionindex'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AppRunArtifact',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    'kind',
                    models.CharField(
                        choices=[
                            ('loaddata_upload', 'Loaddata Upload'),
                            ('dumpdata_export', 'Dumpdata Export'),
                        ],
                        max_length=32,
                    ),
                ),
                ('filename', models.CharField(max_length=255)),
                ('content_type', models.CharField(default='application/json', max_length=100)),
                ('size', models.PositiveIntegerField(default=0)),
                ('content', models.BinaryField()),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'app',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='run_artifacts',
                        to='apps.app',
                    ),
                ),
                (
                    'created_by',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='app_run_artifacts',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'App Run Artifact',
                'verbose_name_plural': 'App Run Artifacts',
                'db_table': 'app_run_artifacts',
            },
        ),
        migrations.AddIndex(
            model_name='apprunartifact',
            index=models.Index(fields=['app', 'kind'], name='idx_run_art_app_kind'),
        ),
        migrations.AddIndex(
            model_name='apprunartifact',
            index=models.Index(fields=['created_by', 'created_at'], name='idx_run_art_user_created'),
        ),
    ]
