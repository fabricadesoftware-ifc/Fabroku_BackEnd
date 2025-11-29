from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework_simplejwt.views import TokenObtainPairView

# from config.permission import CustomUserPermission
from .models import User
from .serializers import UserRetrieveSerializer, UserSerializer


@extend_schema(tags=['users'])
class UserViewSet(ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    # permission_classes = [CustomUserPermission]

    def get_serializer_class(self):  # type: ignore
        if self.action == 'retrieve':
            return UserRetrieveSerializer
        return UserSerializer

    @action(detail=False, methods=['get'])
    def me(self, request):
        user = request.user
        serializer = UserRetrieveSerializer(user)
        return Response(serializer.data)
