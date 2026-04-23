from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('auth_user', '0006_clitoken'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='custom_max_apps',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Sobrescreve o limite padrão de apps para este usuário. Deixe vazio para usar o padrão do perfil.',
                null=True,
                verbose_name='limite personalizado de apps',
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='custom_max_services',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Sobrescreve o limite padrão de serviços para este usuário. Deixe vazio para usar o padrão do perfil.',
                null=True,
                verbose_name='limite personalizado de serviços',
            ),
        ),
    ]
