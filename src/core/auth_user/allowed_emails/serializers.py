from rest_framework import serializers

from .models import AllowedEmail


class AllowedEmailSerializer(serializers.ModelSerializer):
    """Serializer para o modelo AllowedEmail."""

    class Meta:
        model = AllowedEmail
        fields = ['id', 'email', 'name', 'is_active', 'notes', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_email(self, value):
        """Normaliza o email para lowercase."""
        return value.lower().strip()


class AllowedEmailCreateSerializer(serializers.ModelSerializer):
    """Serializer para criação de AllowedEmail."""

    class Meta:
        model = AllowedEmail
        fields = ['email', 'name', 'notes']

    def validate_email(self, value):
        """Valida e normaliza o email."""
        email = value.lower().strip()

        # Verifica se já existe
        if AllowedEmail.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError('Este email já está na lista de permitidos.')

        return email
