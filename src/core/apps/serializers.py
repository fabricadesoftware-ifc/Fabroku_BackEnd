from rest_framework import serializers

from core.apps.mixins.app import AppMixin
from core.apps.models import App


class AppSerializer(serializers.ModelSerializer):
    class Meta:
        model = App
        fields = [
            'id',
            'name',
            'git',
            'project',
            'created_at',
            'updated_at',
            'status',
            'domain',
            'port',
            'variables',
            'task_id',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'status', 'domain', 'port']

    def create(self, validated_data):
        user = self.context['request'].user
        instance = super().create(validated_data)

        task_result = AppMixin.create_app.delay(app_id=instance.id, user_id=user.id)  # type: ignore

        instance.task_id = task_result.id
        instance.save()

        return instance

    def update(self, instance, validated_data):
        return AppMixin().update_app(
            name=validated_data.get('name', instance.name),
            git=validated_data.get('git', instance.git),
            id=instance.id,
        )

    def destroy(self, instance):
        return AppMixin().delete_app(
            id=instance.id,
        )
