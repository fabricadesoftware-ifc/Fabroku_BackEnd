from rest_framework import serializers

from core.auth_user.models import User
from core.project.models import Project


class ProjectUserSerializer(serializers.ModelSerializer):
    """Serializer resumido do usuário para exibir dentro de projetos."""

    class Meta:
        model = User
        fields = ['id', 'name', 'email', 'avatar_url']


class ProjectSerializer(serializers.ModelSerializer):
    users = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), many=True)
    users_detail = ProjectUserSerializer(source='users', many=True, read_only=True)
    is_owner = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            'id',
            'name',
            'users',
            'users_detail',
            'is_owner',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'is_owner', 'users_detail', 'created_at', 'updated_at']

    def get_is_owner(self, obj):
        """Retorna True se o usuário logado é dono do projeto."""
        request = self.context.get('request')
        if request and request.user:
            return obj.users.filter(id=request.user.id).exists()
        return False
