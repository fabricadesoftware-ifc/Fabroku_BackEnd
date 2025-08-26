from __future__ import annotations

from typing import Any, Dict, Optional

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from fabroku.application.use_cases import (
	DeployAppUseCase,
	InstallPluginUseCase,
	CreatePostgresUseCase,
	LinkPostgresUseCase,
	CreateRabbitMQUseCase,
	LinkRabbitMQUseCase,
	ConfigSetUseCase,
	ProxyPortsSetUseCase,
	ProxyPortsAddUseCase,
	ProxyPortsClearUseCase,
	SmartDeployUseCase,
	DeployStateSync,
)
from fabroku.infrastructure.adapters.dokku_shell_adapter import DokkuShellAdapter
from .models import Deploy


class BaseDokkuAPIView(APIView):
	def get_services(self) -> Dict[str, Any]:
		dokku = DokkuShellAdapter()
		return {
			"deploy": DeployAppUseCase(dokku),
			"plugin_install": InstallPluginUseCase(dokku),
			"pg_create": CreatePostgresUseCase(dokku),
			"pg_link": LinkPostgresUseCase(dokku),
			"rmq_create": CreateRabbitMQUseCase(dokku),
			"rmq_link": LinkRabbitMQUseCase(dokku),
			"config_set": ConfigSetUseCase(dokku),
			"ports_set": ProxyPortsSetUseCase(dokku),
			"ports_add": ProxyPortsAddUseCase(dokku),
			"ports_clear": ProxyPortsClearUseCase(dokku),
			"smart_deploy": SmartDeployUseCase(dokku),
		}


class CreateAppView(BaseDokkuAPIView):
	def post(self, request):
		app_name: str = request.data.get("app_name")
		initial_env: Optional[Dict[str, str]] = request.data.get("initial_env")
		if not app_name:
			return Response({"detail": "'app_name' é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
		services = self.get_services()
		result = services["create"].execute(app_name=app_name, initial_environment=initial_env)
		return Response({"success": result.success, "message": result.message}, status=status.HTTP_200_OK if result.success else status.HTTP_400_BAD_REQUEST)


class DeployView(BaseDokkuAPIView):
	def post(self, request):
		app_name: str = request.data.get("app_name")
		git_url: Optional[str] = request.data.get("git_url")
		image: Optional[str] = request.data.get("image")
		buildpack: Optional[str] = request.data.get("buildpack")
		if not app_name:
			return Response({"detail": "'app_name' é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
		services = self.get_services()
		result = services["deploy"].execute(app_name=app_name, git_url=git_url, image=image, buildpack=buildpack)
		return Response({"success": result.success, "message": result.message}, status=status.HTTP_200_OK if result.success else status.HTTP_400_BAD_REQUEST)


class SmartDeployView(BaseDokkuAPIView):
	def post(self, request):
		app_name: str = request.data.get("app_name")
		git_url: Optional[str] = request.data.get("git_url")
		buildpack: Optional[str] = request.data.get("buildpack")
		if not app_name or not git_url:
			return Response({"detail": "'app_name' e 'git_url' são obrigatórios."}, status=status.HTTP_400_BAD_REQUEST)

		deploy = Deploy.objects.create(app_name=app_name, github_repo=git_url, status="rascunho")

		services = self.get_services()
		use_case: SmartDeployUseCase = services["smart_deploy"]

		class _DjangoState(DeployStateSync):
			def __init__(self, deploy_obj: Deploy) -> None:
				self.deploy = deploy_obj

			def set_status(self, s: str) -> None:
				Deploy.objects.filter(pk=self.deploy.pk).update(status=s)

			def set_analysis(self, a: Dict) -> None:
				Deploy.objects.filter(pk=self.deploy.pk).update(analysis=a)

			def append_log(self, line: str) -> None:
				obj = Deploy.objects.get(pk=self.deploy.pk)
				new_logs = (obj.logs or "") + ("\n" if obj.logs else "") + line
				Deploy.objects.filter(pk=self.deploy.pk).update(logs=new_logs)

			def set_error(self, err_msg: str) -> None:
				Deploy.objects.filter(pk=self.deploy.pk).update(error_message=err_msg)

		state = _DjangoState(deploy)
		state.set_status("em_andamento")

		result = use_case.execute(app_name=app_name, git_url=git_url, state_sync=state, buildpack=buildpack)

		return Response({
			"success": result.success,
			"message": result.message,
			"deploy_id": deploy.id,
		}, status=status.HTTP_200_OK if result.success else status.HTTP_400_BAD_REQUEST)


class DeleteAppView(BaseDokkuAPIView):
	def delete(self, request, app_name: str):
		force: bool = request.query_params.get("force", "true").lower() == "true"
		services = self.get_services()
		result = services["delete"].execute(app_name=app_name, force=force)
		return Response({"success": result.success, "message": result.message}, status=status.HTTP_200_OK if result.success else status.HTTP_400_BAD_REQUEST)


class PluginInstallView(BaseDokkuAPIView):
	def post(self, request):
		plugin_git_url: str = request.data.get("plugin_git_url")
		name: Optional[str] = request.data.get("name")
		if not plugin_git_url:
			return Response({"detail": "'plugin_git_url' é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
		services = self.get_services()
		result = services["plugin_install"].execute(plugin_git_url=plugin_git_url, name=name)
		return Response({"success": result.success, "message": result.message}, status=status.HTTP_200_OK if result.success else status.HTTP_400_BAD_REQUEST)


class PostgresCreateView(BaseDokkuAPIView):
	def post(self, request):
		service_name: str = request.data.get("service_name")
		options = request.data.get("options") or []
		if not service_name:
			return Response({"detail": "'service_name' é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
		services = self.get_services()
		result = services["pg_create"].execute(service_name=service_name, options=options)
		return Response({"success": result.success, "message": result.message}, status=status.HTTP_200_OK if result.success else status.HTTP_400_BAD_REQUEST)


class PostgresLinkView(BaseDokkuAPIView):
	def post(self, request):
		service_name: str = request.data.get("service_name")
		app_name: str = request.data.get("app_name")
		if not service_name or not app_name:
			return Response({"detail": "'service_name' e 'app_name' são obrigatórios."}, status=status.HTTP_400_BAD_REQUEST)
		services = self.get_services()
		result = services["pg_link"].execute(service_name=service_name, app_name=app_name)
		return Response({"success": result.success, "message": result.message}, status=status.HTTP_200_OK if result.success else status.HTTP_400_BAD_REQUEST)


class RabbitMQCreateView(BaseDokkuAPIView):
	def post(self, request):
		service_name: str = request.data.get("service_name")
		options = request.data.get("options") or []
		if not service_name:
			return Response({"detail": "'service_name' é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
		services = self.get_services()
		result = services["rmq_create"].execute(service_name=service_name, options=options)
		return Response({"success": result.success, "message": result.message}, status=status.HTTP_200_OK if result.success else status.HTTP_400_BAD_REQUEST)


class RabbitMQLinkView(BaseDokkuAPIView):
	def post(self, request):
		service_name: str = request.data.get("service_name")
		app_name: str = request.data.get("app_name")
		if not service_name or not app_name:
			return Response({"detail": "'service_name' e 'app_name' são obrigatórios."}, status=status.HTTP_400_BAD_REQUEST)
		services = self.get_services()
		result = services["rmq_link"].execute(service_name=service_name, app_name=app_name)
		return Response({"success": result.success, "message": result.message}, status=status.HTTP_200_OK if result.success else status.HTTP_400_BAD_REQUEST)


class ConfigSetView(BaseDokkuAPIView):
	def post(self, request):
		app_name: str = request.data.get("app_name")
		env: Dict[str, str] = request.data.get("env") or {}
		if not app_name:
			return Response({"detail": "'app_name' é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
		services = self.get_services()
		result = services["config_set"].execute(app_name=app_name, env_vars=env)
		return Response({"success": result.success, "message": result.message}, status=status.HTTP_200_OK if result.success else status.HTTP_400_BAD_REQUEST)


class PortsSetView(BaseDokkuAPIView):
	def post(self, request):
		app_name: str = request.data.get("app_name")
		mappings = request.data.get("mappings") or []
		if not app_name:
			return Response({"detail": "'app_name' é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
		services = self.get_services()
		result = services["ports_set"].execute(app_name=app_name, mappings=mappings)
		return Response({"success": result.success, "message": result.message}, status=status.HTTP_200_OK if result.success else status.HTTP_400_BAD_REQUEST)


class PortsAddView(BaseDokkuAPIView):
	def post(self, request):
		app_name: str = request.data.get("app_name")
		mappings = request.data.get("mappings") or []
		if not app_name:
			return Response({"detail": "'app_name' é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
		services = self.get_services()
		result = services["ports_add"].execute(app_name=app_name, mappings=mappings)
		return Response({"success": result.success, "message": result.message}, status=status.HTTP_200_OK if result.success else status.HTTP_400_BAD_REQUEST)


class PortsClearView(BaseDokkuAPIView):
	def post(self, request):
		app_name: str = request.data.get("app_name")
		if not app_name:
			return Response({"detail": "'app_name' é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)
		services = self.get_services()
		result = services["ports_clear"].execute(app_name=app_name)
		return Response({"success": result.success, "message": result.message}, status=status.HTTP_200_OK if result.success else status.HTTP_400_BAD_REQUEST)
