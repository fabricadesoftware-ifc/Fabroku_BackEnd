from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from .models import AllowedEmail
from .serializers import AllowedEmailCreateSerializer, AllowedEmailSerializer


class AllowedEmailViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gerenciar emails permitidos.
    Apenas administradores podem gerenciar a lista.
    """

    queryset = AllowedEmail.objects.all()
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get_serializer_class(self):
        if self.action == 'create':
            return AllowedEmailCreateSerializer
        return AllowedEmailSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filtro por status ativo
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        # Busca por email
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(email__icontains=search)

        return queryset

    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """Ativa/desativa um email."""
        allowed_email = self.get_object()
        allowed_email.is_active = not allowed_email.is_active
        allowed_email.save()
        return Response(AllowedEmailSerializer(allowed_email).data)

    @action(detail=False, methods=['post'])
    def bulk_create(self, request):
        """
        Cria múltiplos emails de uma vez.
        Espera um array de objetos com email, name (opcional), notes (opcional).
        """
        emails_data = request.data.get('emails', [])
        if not emails_data:
            return Response(
                {'error': 'Lista de emails é obrigatória'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = []
        errors = []

        for item in emails_data:
            email = item.get('email', '').lower().strip()
            if not email:
                continue

            if AllowedEmail.objects.filter(email__iexact=email).exists():
                errors.append({'email': email, 'error': 'Já existe'})
                continue

            allowed_email = AllowedEmail.objects.create(
                email=email,
                name=item.get('name'),
                notes=item.get('notes'),
            )
            created.append(AllowedEmailSerializer(allowed_email).data)

        return Response({
            'created': created,
            'errors': errors,
            'total_created': len(created),
            'total_errors': len(errors),
        })

    @action(detail=False, methods=['get'])
    def check_email(self, request):
        """
        Verifica se um email está na lista de permitidos.
        Útil para verificações rápidas.
        """
        email = request.query_params.get('email', '').lower().strip()
        if not email:
            return Response(
                {'error': 'Email é obrigatório'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_allowed = AllowedEmail.objects.is_email_allowed(email)
        return Response({
            'email': email,
            'is_allowed': is_allowed,
        })
