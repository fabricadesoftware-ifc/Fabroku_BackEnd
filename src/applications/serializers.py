import re

from django.conf import settings
from django.db import models
from rest_framework import serializers

from applications.domain.exceptions import ApplicationDomainError, AppLimitExceeded, AppNameConflict
from applications.domain.validators import (
    RESERVED_ENV_VAR_PREFIXES,
    validate_app_name,
    validate_app_name_available,
)
from applications.models import App, AppProcessScale
from applications.process_scale import validate_process_quantities
from applications.tasks import create_app_task, update_app_task
from applications.use_cases.register_app import RegisterAppCommand, RegisterAppUseCase
from core.apps.utils import slugify_dokku
from interactive_sessions.models import InteractiveRunCommandKind
from service_mgmt.serializers import ServiceSerializer

ENV_VAR_KEY_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
ENV_VAR_MAX_ITEMS = 100
ENV_VAR_MAX_KEY_LENGTH = 128
ENV_VAR_MAX_VALUE_LENGTH = 8192
# Nome de branch/ref: vai direto para `dokku git:sync ... <branch>` via SSH, sem aspas.
# Mesmo alfabeto que o plugin fabroku aceita (fn-fabroku-validate-branch).
GIT_BRANCH_PATTERN = re.compile(r'^[A-Za-z0-9._/-]+$')
GIT_BRANCH_MAX_LENGTH = 255


class InteractiveSessionCreateSerializer(serializers.Serializer):
    command_kind = serializers.ChoiceField(choices=InteractiveRunCommandKind.choices)
    manage_path = serializers.CharField(required=False, allow_blank=False, default='manage.py')
    service_id = serializers.IntegerField(required=False)


class InteractiveSessionAnswerSerializer(serializers.Serializer):
    prompt_id = serializers.CharField()
    value = serializers.CharField(allow_blank=True)


class InteractiveSessionInputSerializer(serializers.Serializer):
    data = serializers.CharField(allow_blank=True, trim_whitespace=False)


class ScaleProcessesSerializer(serializers.Serializer):
    processes = serializers.DictField()

    def validate_processes(self, value):
        try:
            return validate_process_quantities(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class EnvVarsUpdateSerializer(serializers.Serializer):
    variables = serializers.DictField(
        child=serializers.CharField(allow_blank=True, trim_whitespace=False),
        allow_empty=True,
    )
    restart = serializers.BooleanField(required=False, default=True)

    def validate_variables(self, value):
        if len(value) > ENV_VAR_MAX_ITEMS:
            raise serializers.ValidationError(f'Informe no maximo {ENV_VAR_MAX_ITEMS} variaveis.')

        normalized = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()
            env_value = '' if raw_value is None else str(raw_value)

            if not key:
                raise serializers.ValidationError('Variavel sem chave.')
            if len(key) > ENV_VAR_MAX_KEY_LENGTH:
                raise serializers.ValidationError(f'{key} excede {ENV_VAR_MAX_KEY_LENGTH} caracteres.')
            if not ENV_VAR_KEY_PATTERN.match(key):
                raise serializers.ValidationError(f'Nome de variavel invalido: {key}')
            if key.upper().startswith(RESERVED_ENV_VAR_PREFIXES):
                raise serializers.ValidationError(f'{key}: prefixo reservado para a plataforma (DOKKU_).')
            if len(env_value) > ENV_VAR_MAX_VALUE_LENGTH:
                raise serializers.ValidationError(f'{key} excede {ENV_VAR_MAX_VALUE_LENGTH} caracteres.')

            normalized[key] = env_value

        return normalized


class AppSerializer(serializers.ModelSerializer):
    is_owner = serializers.SerializerMethodField()
    services = ServiceSerializer(many=True, read_only=True)
    # DRF auto-generates a UniqueValidator from the model's UniqueConstraint(fields=['name'],
    # condition=Q(deleted_at__isnull=True)) but ignores the `condition` — it would treat `name`
    # as globally unique across ALL apps, including soft-deleted ones, permanently blocking reuse
    # of a deleted app's name. Declaring the field explicitly (no validators) drops that incorrect
    # auto-validator; RegisterAppUseCase enforces the real (condition-respecting) uniqueness rule.
    name = serializers.CharField(max_length=255)

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

    def validate_variables(self, value):
        """Mesmas regras do endpoint env_vars (chave valida, sem prefixo DOKKU_, limites)."""
        if not value:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('variables deve ser um objeto chave/valor.')
        return EnvVarsUpdateSerializer().validate_variables(value)

    def validate_branch(self, value):
        """Branch segue sem aspas para `dokku git:sync`: só caracteres de ref Git, sem flags."""
        branch = (value or '').strip()
        if not branch:
            raise serializers.ValidationError('Branch não pode ser vazia.')
        if len(branch) > GIT_BRANCH_MAX_LENGTH:
            raise serializers.ValidationError(f'Branch excede {GIT_BRANCH_MAX_LENGTH} caracteres.')
        if not GIT_BRANCH_PATTERN.match(branch) or branch.startswith('-') or '..' in branch:
            raise serializers.ValidationError(
                'Branch inválida: use apenas letras, números, ".", "_", "-" e "/", sem começar com "-".'
            )
        return branch

    def validate_project(self, project):
        """Só membros do projeto (ou admins) podem criar/mover apps nele."""
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        if user is None or getattr(user, 'is_superuser', False):
            return project
        if self.instance is not None and self.instance.project_id == project.id:
            return project
        if not project.users.filter(id=user.id).exists():
            raise serializers.ValidationError('Você não é membro deste projeto.')
        return project

    def validate_name_dokku(self, value):
        """Apenas perfis privilegiados ou admins podem definir nome personalizado.

        O name_dokku é o nome real do app no servidor Dokku: ele vai para `apps:destroy`,
        `config:set`, `run` etc. Por isso ele é imutável depois do provisionamento e passa
        pelas mesmas regras de nome do RegisterAppUseCase (slug canônico, nomes reservados
        como `fabroku-api`, sem colidir com outro app ativo). Sem isso um membro da fábrica
        conseguia apontar o próprio registro para o container de outro app, ou do próprio
        Fabroku, e operar nele.
        """
        request = self.context.get('request')
        if request and request.user:
            is_fabric = getattr(request.user, 'is_fabric', False)
            if not is_fabric and not request.user.is_superuser:
                raise serializers.ValidationError(
                    f'Apenas {settings.FABROKU_PRIVILEGED_ROLE_LABEL} ou administradores podem '
                    'personalizar o nome do app.'
                )

        if not value:
            return value

        slug = slugify_dokku(str(value))
        if self.instance is not None and self.instance.name_dokku and slug != self.instance.name_dokku:
            raise serializers.ValidationError(
                'O nome Dokku não pode ser alterado depois do app ter sido provisionado.'
            )

        try:
            validate_app_name(slug)
            validate_app_name_available(slug)
        except ApplicationDomainError as exc:
            raise serializers.ValidationError(str(exc)) from exc

        conflicts = App.objects.filter(deleted_at__isnull=True).filter(
            models.Q(name__iexact=slug) | models.Q(name_dokku__iexact=slug)
        )
        if self.instance is not None:
            conflicts = conflicts.exclude(pk=self.instance.pk)
        if conflicts.exists():
            raise serializers.ValidationError(f'Já existe um app chamado "{slug}".')

        return slug

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

        try:
            instance = RegisterAppUseCase().execute(
                RegisterAppCommand(
                    user_id=user.id,
                    project_id=str(validated_data['project'].id),
                    app_name=validated_data['name'],
                    git_url=validated_data['git'],
                    git_branch=validated_data.get('branch', 'main'),
                    env_vars=validated_data.get('variables'),
                    name_dokku=validated_data.get('name_dokku'),
                )
            )
        except AppLimitExceeded as exc:
            raise serializers.ValidationError({
                'quota': f'Limite de apps atingido ({exc.current}/{exc.limit}). '
                'Entre em contato com um administrador para aumentar seu limite.',
                'limit': exc.limit,
                'current': exc.current,
            })
        except AppNameConflict as exc:
            raise serializers.ValidationError({'name': f'Já existe um app chamado "{exc.name}".'})

        task_result = create_app_task.delay(
            app_id=instance.id, user_id=user.id, env_vars=instance.variables
        )

        instance.task_id = task_result.id
        instance.status = 'STARTING'
        instance.save()

        return instance


class AppProcessScaleSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField(source='desired_quantity', read_only=True)

    class Meta:
        model = AppProcessScale
        fields = [
            'id',
            'process_name',
            'quantity',
            'desired_quantity',
            'current_quantity',
            'detected_at',
            'last_synced_at',
            'updated_at',
        ]
        read_only_fields = fields

    def update(self, instance, validated_data):
        update_app_task.delay(
            name=validated_data.get('name', instance.name),
            git=validated_data.get('git', instance.git),
            app_id=instance.id,
            env_vars=validated_data.get('variables', instance.variables),
        )

        return instance
