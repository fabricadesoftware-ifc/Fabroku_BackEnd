from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('service_mgmt', '0003_alter_service_project'),
    ]

    operations = [
        migrations.AlterField(
            model_name='service',
            name='service_type',
            field=models.CharField(
                choices=[
                    ('postgres', 'Postgres'),
                    ('postgis', 'PostGIS'),
                    ('rabbitmq', 'RabbitMQ'),
                    ('redis', 'Redis'),
                    ('s3', 'Armazenamento S3'),
                ],
                max_length=50,
            ),
        ),
    ]
