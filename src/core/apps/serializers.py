from rest_framework import serializers
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
        return App.objects.create(**validated_data)
