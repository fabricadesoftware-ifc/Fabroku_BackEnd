from django.urls import path
from .views import (
	CreateAppView,
	DeployView,
	DeleteAppView,
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
)

urlpatterns = [
	path("dokku/apps/create/", CreateAppView.as_view(), name="dokku-create-app"),
	path("dokku/deploy/", DeployView.as_view(), name="dokku-deploy"),
	path("dokku/smart-deploy/", SmartDeployView.as_view(), name="dokku-smart-deploy"),
	path("dokku/apps/<str:app_name>/", DeleteAppView.as_view(), name="dokku-delete-app"),
	path("dokku/plugins/install/", PluginInstallView.as_view(), name="dokku-plugin-install"),
	path("dokku/postgres/create/", PostgresCreateView.as_view(), name="dokku-postgres-create"),
	path("dokku/postgres/link/", PostgresLinkView.as_view(), name="dokku-postgres-link"),
	path("dokku/rabbitmq/create/", RabbitMQCreateView.as_view(), name="dokku-rabbitmq-create"),
	path("dokku/rabbitmq/link/", RabbitMQLinkView.as_view(), name="dokku-rabbitmq-link"),
	path("dokku/config/set/", ConfigSetView.as_view(), name="dokku-config-set"),
	path("dokku/ports/set/", PortsSetView.as_view(), name="dokku-ports-set"),
	path("dokku/ports/add/", PortsAddView.as_view(), name="dokku-ports-add"),
	path("dokku/ports/clear/", PortsClearView.as_view(), name="dokku-ports-clear"),
] 