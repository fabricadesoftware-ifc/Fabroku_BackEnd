import uuid

from django.db import transaction
from rest_framework import serializers

from applications.models import App
from core.apps.mixins.services.service_env import allocate_attached_service_name, allocate_service_env_key
from service_mgmt.models import Service
from service_mgmt.service_types import get_service_runtime, is_postgres_runtime, is_supported_service_type
from service_mgmt.tasks import create_service_standalone_task, create_service_task


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
            'env_key',
            'image',
            'image_version',
            'host',
            'port',
            'task_id',
            'created_at',
            'updated_at',
        ]
        extra_kwargs = {
            'name': {'required': False, 'allow_blank': True},
            'project': {'required': False},
        }
        read_only_fields = [
            'id',
            'host',
            'port',
            'container_name',
            'env_key',
            'image',
            'image_version',
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
            raise serializers.ValidationError('Apenas PostgreSQL, PostGIS e Redis estao habilitados no momento.')

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
            password = uuid.uuid4().hex if is_postgres_runtime(runtime) else ''
            with transaction.atomic():
                locked_app = App.objects.select_for_update().get(id=app.id)
                service_name = allocate_attached_service_name(
                    app=locked_app,
                    base_name=f'{locked_app.name}-{runtime.attached_suffix}',
                )
                env_key = allocate_service_env_key(
                    app=locked_app,
                    service_name=service_name,
                    runtime=runtime,
                )
                placeholder = Service.objects.create(
                    name=service_name,
                    service_type=service_type,
                    user=runtime.user,
                    password=password,
                    host='provisionando...',
                    port=runtime.port,
                    app=locked_app,
                    project=locked_app.project,
                    env_key=env_key,
                    image=runtime.image,
                    image_version=runtime.image_version,
                )

            try:
                task_result = create_service_task.delay(
                    app_id=app.id,
                    service_type=service_type,
                    service_id=placeholder.id,
                )
            except Exception:
                placeholder.delete()
                raise

            placeholder.task_id = task_result.id
            placeholder.save(update_fields=['task_id'])
            locked_app.task_id = task_result.id
            locked_app.save(update_fields=['task_id'])
            return placeholder

        password = uuid.uuid4().hex if is_postgres_runtime(runtime) else ''
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
            image=runtime.image,
            image_version=runtime.image_version,
            task_id=None,
        )
        task_result = create_service_standalone_task.delay(
            project_id=project.id,
            service_type=service_type,
            name=name,
            service_id=placeholder.id,
            password=password,
        )
        placeholder.task_id = task_result.id
        placeholder.save(update_fields=['task_id'])
        return placeholder
