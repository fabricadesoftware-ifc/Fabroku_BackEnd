from rest_framework import serializers

from core.apps.mixins import AppMixin
from core.apps.models import App, Service


class ServiceSerializer(serializers.ModelSerializer):
    """Serializer para serviços (banco de dados, redis, etc.)."""

    class Meta:
        model = Service
        fields = [
            'id',
            'name',
            'service_type',
            'app',
            'project',
            'container_name',
            'host',
            'port',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'name',
            'host',
            'port',
            'container_name',
            'project',
            'created_at',
            'updated_at',
        ]

    def create(self, validated_data):
        app = validated_data['app']
        service_type = validated_data['service_type']

        # Dispara a task Celery para criar o serviço
        task_result = AppMixin.create_service.delay(
            app_id=app.id,
            service_type=service_type,
        )  # type: ignore

        # Atualiza task_id no app para tracking
        app.task_id = task_result.id
        app.save(update_fields=['task_id'])

        # Retorna uma instância temporária para a response
        # (o serviço real será criado pela task)
        return Service(
            name=f'{app.name}-db',
            service_type=service_type,
            app=app,
            project=app.project,
            host='provisionando...',
            port=0,
        )


class AppSerializer(serializers.ModelSerializer):
    is_owner = serializers.SerializerMethodField()
    services = ServiceSerializer(source='service_set', many=True, read_only=True)

    class Meta:
        model = App
        fields = [
            'id',
            'name',
            'git',
            'branch',
            'project',
            'is_owner',
            'created_at',
            'updated_at',
            'status',
            'domain',
            'port',
            'variables',
            'task_id',
            'name_dokku',
            'services',
        ]
        read_only_fields = [
            'id',
            'is_owner',
            'created_at',
            'updated_at',
            'status',
            'domain',
            'port',
            'task_id',
            'services',
        ]

    def validate_name_dokku(self, value):
        """Apenas membros da fábrica ou admins podem definir nome personalizado."""
        request = self.context.get('request')
        if request and request.user:
            is_fabric = getattr(request.user, 'is_fabric', False)
            if not is_fabric and not request.user.is_superuser:
                raise serializers.ValidationError(
                    'Apenas membros da Fábrica ou administradores podem personalizar o nome do app.'
                )
        return value

    def get_is_owner(self, obj):
        """Retorna True se o usuário logado é dono do app (via projeto)."""
        request = self.context.get('request')
        if request and request.user:
            return obj.project.users.filter(id=request.user.id).exists()
        return False

    def create(self, validated_data):
        user = self.context['request'].user
        instance = super().create(validated_data)

        task_result = AppMixin.create_app.delay(app_id=instance.id, user_id=user.id)  # type: ignore

        instance.task_id = task_result.id
        instance.status = 'STARTING'
        instance.save()

        return instance

    def update(self, instance, validated_data):
        AppMixin.update_app.delay(
            name=validated_data.get('name', instance.name),
            git=validated_data.get('git', instance.git),
            app_id=instance.id,
            env_vars=validated_data.get('variables', instance.variables),
        )  # type: ignore  # noqa: E501

        return instance
