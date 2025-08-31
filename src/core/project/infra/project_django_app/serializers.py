from rest_framework import serializers
from core.project.infra.project_django_app.models import Network, Project


class NetworkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Network
        fields = ['id', 'name', 'description']


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = [
            'id',
            'user',
            'name',
            'description',
            'technology',
            'source_type',
            'source_git',
            'source_docker',
            'network',
            'port',
            'variables',
            'domain',
            'status',
            'creation_date',
            'last_update_date',
        ]
        read_only_fields = ['user', 'domain', 'status', 'creation_date', 'last_update_date', 'source_type'] 