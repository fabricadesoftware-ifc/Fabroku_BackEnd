from rest_framework import serializers

from core.auth_user.models import User
from core.project.models import Project


class ProjectSerializer(serializers.ModelSerializer):
    users = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), many=True)
    is_owner = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            'id',
            'name',
            'users',
            'is_owner',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'is_owner', 'created_at', 'updated_at']
        depth = 1

    def get_is_owner(self, obj):
        """Retorna True se o usuário logado é dono do projeto."""
        request = self.context.get('request')
        if request and request.user:
            return obj.users.filter(id=request.user.id).exists()
        return False
