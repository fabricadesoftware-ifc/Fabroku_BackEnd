import uuid

from rest_framework import serializers

from core.apps.mixins import AppMixin
from core.apps.models import App, Service, ServiceType


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
            'task_id',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'host',
            'port',
            'container_name',
            'task_id',
            'created_at',
            'updated_at',
        ]

    def validate(self, attrs):
        """Valida criação: app OU (project + service_type) para standalone."""
        if self.instance:
            return attrs
        app = attrs.get('app')
        project = attrs.get('project')
        service_type = attrs.get('service_type')

        if app:
            if not project:
                attrs['project'] = app.project
            return attrs

        if not project or not service_type:
            raise serializers.ValidationError(
                'Para criar serviço standalone, informe project e service_type. '
                'Para vincular a um app, informe app e service_type.'
            )
        if service_type != ServiceType.POSTGRES:
            raise serializers.ValidationError('Apenas Postgres está habilitado no momento.')
        return attrs

    def create(self, validated_data):
        # Validação de quota
        request = self.context.get('request')
        if request and request.user:
            user = request.user
            if not user.can_create_service():
                max_services = user.max_services
                current = user.services_count
                raise serializers.ValidationError({
                    'quota': f'Limite de serviços atingido ({current}/{max_services}). '
                    'Entre em contato com um administrador para aumentar seu limite.',
                    'limit': max_services,
                    'current': current,
                })

        app = validated_data.get('app')
        project = validated_data.get('project')
        service_type = validated_data['service_type']
        name = validated_data.get('name')

        if app:
            # Fluxo vinculado: cria serviço no app (task cria no Dokku)
            task_result = AppMixin.create_service.delay(
                app_id=app.id,
                service_type=service_type,
            )  # type: ignore
            app.task_id = task_result.id
            app.save(update_fields=['task_id'])
            return Service(
                name=f'{app.name}-db',
                service_type=service_type,
                app=app,
                project=app.project,
                host='provisionando...',
                port=0,
            )

        # Fluxo standalone: cria placeholder e dispara task
        password = uuid.uuid4().hex
        service_name = name or 'provisionando...'
        placeholder = Service.objects.create(
            name=service_name,
            service_type=service_type,
            user='postgres',
            password=password,
            host='provisionando...',
            port=5432,
            app=None,
            project=project,
            container_name=None,
            task_id=None,
        )
        task_result = AppMixin.create_service_standalone.delay(
            project_id=project.id,
            service_type=service_type,
            name=name,
            service_id=placeholder.id,
            password=password,
        )  # type: ignore
        placeholder.task_id = task_result.id
        placeholder.save(update_fields=['task_id'])
        return placeholder


class AppSerializer(serializers.ModelSerializer):
    is_owner = serializers.SerializerMethodField()
    services = ServiceSerializer(many=True, read_only=True)

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

        # Validação de quota
        if not user.can_create_app():
            max_apps = user.max_apps
            current = user.apps_count
            raise serializers.ValidationError({
                'quota': f'Limite de apps atingido ({current}/{max_apps}). '
                'Entre em contato com um administrador para aumentar seu limite.',
                'limit': max_apps,
                'current': current,
            })

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
