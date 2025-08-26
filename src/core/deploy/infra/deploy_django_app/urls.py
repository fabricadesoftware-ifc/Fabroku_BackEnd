from django.urls import path
from .views import (
	# CreateProjectView,
	DeployView,
	# DeleteProjectView,
	PluginInstallView,
	PostgresCreateView,
	PostgresLinkView,
	RabbitMQCreateView,
	RabbitMQLinkView,
	ConfigSetView,
	PortsSetView,
	PortsAddView,
	PortsClearView,
	SmartDeployView,
	# GetProjectStatusView,
	# ListNetworksView,
	# CreateNetworkView,
	DeleteAppView,
)

urlpatterns = [
	# path("dokku/project/create/", CreateProjectView.as_view(), name="dokku-create-project"),
	path("dokku/deploy/", DeployView.as_view(), name="dokku-deploy"), # Renomeado para app_name
	path("dokku/smart-deploy/", SmartDeployView.as_view(), name="dokku-smart-deploy"), # Renomeado para app_name
	# path("dokku/project/<str:project_name>/destroy/", DeleteProjectView.as_view(), name="dokku-delete-project"),
	# path("dokku/project/<str:project_name>/status/", GetProjectStatusView.as_view(), name="dokku-project-status"),
	
	# path("dokku/networks/", ListNetworksView.as_view(), name="dokku-list-networks"),
	# path("dokku/networks/create/", CreateNetworkView.as_view(), name="dokku-create-network"),

	path("dokku/plugins/install/", PluginInstallView.as_view(), name="dokku-plugin-install"),
	path("dokku/postgres/create/", PostgresCreateView.as_view(), name="dokku-postgres-create"),	
	path("dokku/postgres/link/", PostgresLinkView.as_view(), name="dokku-postgres-link"), # app_name
	path("dokku/rabbitmq/create/", RabbitMQCreateView.as_view(), name="dokku-rabbitmq-create"),
	path("dokku/rabbitmq/link/", RabbitMQLinkView.as_view(), name="dokku-rabbitmq-link"), # app_name
	path("dokku/config/set/", ConfigSetView.as_view(), name="dokku-config-set"), # app_name
	path("dokku/ports/set/", PortsSetView.as_view(), name="dokku-ports-set"), # app_name
	path("dokku/ports/add/", PortsAddView.as_view(), name="dokku-ports-add"), # app_name
	path("dokku/ports/clear/", PortsClearView.as_view(), name="dokku-ports-clear"), # app_name

	path("dokku/apps/<str:app_name>/", DeleteAppView.as_view(), name="dokku-delete-app"),
] 