from rest_framework import serializers

from .models import User


class UserRetrieveSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(read_only=True)
    name = serializers.CharField(read_only=True)
    avatar_url = serializers.URLField(read_only=True)
    is_superuser = serializers.BooleanField(read_only=True)
    is_fabric = serializers.BooleanField(read_only=True)
    date_joined = serializers.DateTimeField(read_only=True)
    last_login = serializers.DateTimeField(read_only=True)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'name',
            'avatar_url',
        ]
