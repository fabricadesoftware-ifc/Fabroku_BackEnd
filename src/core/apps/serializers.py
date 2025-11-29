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
            'project',
            'created_at',
            'updated_at',
            'status',
            'domain',
            'port',
            'variables',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'status', 'domain', 'port']

    def create(self, validated_data):
        return AppMixin().create_app(
            name=validated_data['name'],
            git=validated_data['git'],
            project_id=validated_data['project'].id,
            env_vars=validated_data.get('variables', None),
            user=self.context['request'].user,
        )

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
