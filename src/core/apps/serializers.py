import uuid

from rest_framework import serializers

from core.apps.mixins import AppMixin
from core.apps.models import App, Service, ServiceType
from core.apps.service_types import get_service_runtime, is_supported_service_type


class ServiceSerializer(serializers.ModelSerializer):
    """Serializer para servicos (banco de dados, redis, etc.)."""

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
        """Valida criacao: app OU (project + service_type) para standalone."""
        if self.instance:
            return attrs

        app = attrs.get('app')
        project = attrs.get('project')
        service_type = attrs.get('service_type')

        if service_type and not is_supported_service_type(service_type):
            raise serializers.ValidationError('Apenas Postgres e Redis estao habilitados no momento.')

        if app:
            if not project:
                attrs['project'] = app.project
            return attrs

        if not project or not service_type:
            raise serializers.ValidationError(
                'Para criar servico standalone, informe project e service_type. '
                'Para vincular a um app, informe app e service_type.'
            )
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        if request and request.user:
            user = request.user
            if not user.can_create_service():
                max_services = user.max_services
                current = user.services_count
                raise serializers.ValidationError({
                    'quota': f'Limite de servicos atingido ({current}/{max_services}). '
                    'Entre em contato com um administrador para aumentar seu limite.',
                    'limit': max_services,
                    'current': current,
                })

        app = validated_data.get('app')
        project = validated_data.get('project')
        service_type = validated_data['service_type']
        name = validated_data.get('name')
        runtime = get_service_runtime(service_type)
        service_type = runtime.service_type

        if app:
            task_result = AppMixin.create_service.delay(
                app_id=app.id,
                service_type=service_type,
            )  # type: ignore
            app.task_id = task_result.id
            app.save(update_fields=['task_id'])
            return Service(
                name=f'{app.name}-{runtime.attached_suffix}',
                service_type=service_type,
                app=app,
                project=app.project,
                host='provisionando...',
                port=runtime.port,
            )

        password = uuid.uuid4().hex if service_type == ServiceType.POSTGRES.value else ''
        service_name = name or 'provisionando...'
        placeholder = Service.objects.create(
            name=service_name,
            service_type=service_type,
            user=runtime.user,
            password=password,
            host='provisionando...',
            port=runtime.port,
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
            'last_commit_sha',
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
            'last_commit_sha',
        ]

    def validate_name_dokku(self, value):
        """Apenas membros da fabrica ou admins podem definir nome personalizado."""
        request = self.context.get('request')
        if request and request.user:
            is_fabric = getattr(request.user, 'is_fabric', False)
            if not is_fabric and not request.user.is_superuser:
                raise serializers.ValidationError(
                    'Apenas membros da Fabrica ou administradores podem personalizar o nome do app.'
                )
        return value

    def _get_project_users(self, obj):
        """Reaproveita o prefetch do projeto quando disponivel."""
        project = getattr(obj, 'project', None)
        if not project:
            return []

        prefetched_objects = getattr(project, '_prefetched_objects_cache', {})
        if 'users' in prefetched_objects:
            return prefetched_objects['users']

        return list(project.users.only('id'))

    def get_is_owner(self, obj):
        """Retorna True se o usuario logado e membro do projeto."""
        request = self.context.get('request')
        if request and request.user:
            return any(user.id == request.user.id for user in self._get_project_users(obj))
        return False

    def create(self, validated_data):
        user = self.context['request'].user

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

        task_result = AppMixin.create_app.delay(
            app_id=instance.id, user_id=user.id, env_vars=instance.variables
        )  # type: ignore

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
