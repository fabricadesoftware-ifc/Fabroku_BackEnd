from rest_framework import serializers

from .models import User


class UserRetrieveSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(read_only=True)
    name = serializers.CharField(read_only=True)
    avatar_url = serializers.URLField(read_only=True)
    is_superuser = serializers.BooleanField(read_only=True)
    is_fabric = serializers.BooleanField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    date_joined = serializers.DateTimeField(read_only=True)
    last_login = serializers.DateTimeField(read_only=True)
    max_apps = serializers.IntegerField(read_only=True, allow_null=True)
    max_services = serializers.IntegerField(read_only=True, allow_null=True)
    apps_count = serializers.IntegerField(read_only=True)
    services_count = serializers.IntegerField(read_only=True)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'name',
            'avatar_url',
            'is_active',
        ]


class UserAdminSerializer(serializers.ModelSerializer):
    """Serializer completo para listagem administrativa de usuários."""

    max_apps = serializers.IntegerField(read_only=True, allow_null=True)
    max_services = serializers.IntegerField(read_only=True, allow_null=True)
    apps_count = serializers.IntegerField(read_only=True)
    services_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'name',
            'avatar_url',
            'is_active',
            'is_superuser',
            'is_fabric',
            'custom_max_apps',
            'custom_max_services',
            'max_apps',
            'max_services',
            'apps_count',
            'services_count',
            'date_joined',
            'last_login',
        ]
        read_only_fields = ['id', 'email', 'name', 'avatar_url', 'date_joined', 'last_login']
