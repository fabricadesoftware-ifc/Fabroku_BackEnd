from rest_framework import serializers

from core.apps.mixins import AppMixin
from core.apps.models import App


class AppSerializer(serializers.ModelSerializer):
    class Meta:
        model = App
        fields = [
            'id',
            'name',
            'git',
            'branch',
            'project',
            'created_at',
            'updated_at',
            'status',
            'domain',
            'port',
            'variables',
            'task_id',
            'name_dokku',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'status', 'domain', 'port', 'task_id', 'name_dokku']

    def create(self, validated_data):
        user = self.context['request'].user
        instance = super().create(validated_data)

        task_result = AppMixin.create_app.delay(app_id=instance.id, user_id=user.id)  # type: ignore

        instance.task_id = task_result.id
        instance.status = 'starting'
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
