from __future__ import annotations

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticatedOrReadOnly # Pode ser mais restrito depois

from core.project.infra.project_django_app.models import Network, Projeto
from core.project.infra.project_django_app.serializers import NetworkSerializer, ProjetoSerializer

from fabroku.application.use_cases.create_project import CreateProjectUseCase
from fabroku.application.use_cases.get_project_status import GetProjectStatusUseCase
from fabroku.infrastructure.adapters.dokku_shell_adapter import DokkuShellAdapter
from fabroku.infrastructure.user_store import get_or_create_user_tag
from fabroku.application.use_cases.delete_app import DeleteAppUseCase


class NetworkListCreateView(ListCreateAPIView):
    queryset = Network.objects.all()
    serializer_class = NetworkSerializer


class NetworkRetrieveUpdateDestroyView(RetrieveUpdateDestroyAPIView):
    queryset = Network.objects.all()
    serializer_class = NetworkSerializer
    lookup_field = 'name' # Usar o nome da rede como lookup


class ProjectListCreateView(ListCreateAPIView):
	queryset = Projeto.objects.all()
	serializer_class = ProjetoSerializer
	permission_classes = [IsAuthenticatedOrReadOnly]

	def get_queryset(self):
		# Filtra projetos pelo usuário logado e FABROKU_TAG, se autenticado
		if self.request.user.is_authenticated:
			tag = get_or_create_user_tag(self.request.user.email) # Assuming email is the unique identifier for user
			return Projeto.objects.filter(variaveis_ambiente__FABROKU_TAG=tag, usuario=self.request.user)
		return Projeto.objects.none() # Não retorna projetos para usuários não autenticados

	def perform_create(self, serializer):
		# Lógica de criação usando o CreateProjectUseCase
		user_email = self.request.user.email
		dokku_service = DokkuShellAdapter()
		create_project_use_case = CreateProjectUseCase(dokku_service, Projeto, self.request.user.__class__, Network)

		data = serializer.validated_data
		app_name = data.get("nome") # Assumindo que nome do projeto é o nome da app Dokku
		
		# Gerar ou obter a FABROKU_TAG para o usuário
		user_tag = get_or_create_user_tag(user_email)
		
		# Adicionar FABROKU_TAG às variáveis de ambiente, garantindo que não seja sobrescrita
		variaveis_ambiente = data.get("variaveis_ambiente", {})
		if "FABROKU_TAG" not in variaveis_ambiente:
			variaveis_ambiente["FABROKU_TAG"] = user_tag
		data["variaveis_ambiente"] = variaveis_ambiente

		result = create_project_use_case.execute(
			app_name=app_name,
			user_email=user_email,
			nome=data.get("nome"),
			descricao=data.get("descricao", ""),
			tecnologia=data.get("tecnologia"),
			source_type=data.get("source_type"),
			source_url=data.get("source_url"),
			network_name=data.get("network").name, # Pega o nome da rede do objeto Network
			porta=data.get("porta"),
			variaveis_ambiente=variaveis_ambiente,
		)

		if not result.success:
			raise status.HTTP_400_BAD_REQUEST(detail=result.message)

		# Se o caso de uso for bem-sucedido, finalize a criação do serializer
		serializer.save(usuario=self.request.user, status="rascunho")


class ProjectRetrieveUpdateDestroyView(RetrieveUpdateDestroyAPIView):
	queryset = Projeto.objects.all()
	serializer_class = ProjetoSerializer
	lookup_field = 'nome' # Usar o nome do projeto como lookup
	permission_classes = [IsAuthenticatedOrReadOnly]

	def get_queryset(self):
		# Garante que o usuário só possa acessar seus próprios projetos
		if self.request.user.is_authenticated:
			tag = get_or_create_user_tag(self.request.user.email)
			return Projeto.objects.filter(variaveis_ambiente__FABROKU_TAG=tag, usuario=self.request.user)
		return Projeto.objects.none()

	def perform_destroy(self, instance):
		# Lógica de deleção usando o DeleteAppUseCase
		dokku_service = DokkuShellAdapter()
		delete_app_use_case = DeleteAppUseCase(dokku_service)
		
		# A CLI já pede confirmação, aqui apenas garantimos o ownership
		result = delete_app_use_case.execute(app_name=instance.nome, force=True) # Força a deleção na API
		if not result.success:
			raise status.HTTP_400_BAD_REQUEST(detail=result.message)
		instance.delete()


class ProjectStatusView(APIView):
	permission_classes = [IsAuthenticatedOrReadOnly]

	def get(self, request, project_name: str) -> Response:
		if not request.user.is_authenticated:
			return Response({"detail": "Autenticação necessária."}, status=status.HTTP_401_UNAUTHORIZED)

		services = {
			"get_project_status": GetProjectStatusUseCase(Projeto),
		}

		use_case: GetProjectStatusUseCase = services["get_project_status"]
		status_result = use_case.execute(project_name=project_name, user_email=request.user.email)

		if not status_result:
			return Response({"detail": f"Projeto '{project_name}' não encontrado ou você não tem permissão."}, status=status.HTTP_404_NOT_FOUND)

		# Retorna o status formatado
		return Response({
			"name": status_result.name,
			"ready": status_result.ready,
			"estado": status_result.estado,
			"age": status_result.age,
		}) 