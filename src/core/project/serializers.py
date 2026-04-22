from rest_framework import serializers

from core.auth_user.models import User
from core.project.models import Project


class ProjectUserSerializer(serializers.ModelSerializer):
    """Serializer resumido do usuario para exibir dentro de projetos."""

    class Meta:
        model = User
        fields = ['id', 'name', 'email', 'avatar_url']


class ProjectSerializer(serializers.ModelSerializer):
    users = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), many=True, required=False)
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

    def _get_project_users(self, obj):
        prefetched_users = getattr(obj, '_prefetched_objects_cache', {}).get('users')
        if prefetched_users is not None:
            return prefetched_users
        return obj.users.all()

    def get_is_owner(self, obj):
        """Retorna True se o usuario logado faz parte do projeto."""
        request = self.context.get('request')
        if request and request.user:
            return any(user.id == request.user.id for user in self._get_project_users(obj))
        return False

    def validate(self, attrs):
        request = self.context.get('request')
        users = attrs.get('users')

        if users is None:
            return attrs

        if not users:
            raise serializers.ValidationError({
                'users': 'O projeto precisa ter pelo menos um membro.',
            })

        if (
            request
            and request.user
            and not getattr(request.user, 'is_superuser', False)
            and self.instance
            and self.instance.users.filter(id=request.user.id).exists()
            and not any(user.id == request.user.id for user in users)
        ):
            raise serializers.ValidationError({
                'users': 'Voce nao pode remover a si mesmo do projeto.',
            })

        return attrs
