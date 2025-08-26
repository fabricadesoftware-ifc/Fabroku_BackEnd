from django.urls import path
from .views import NetworkListCreateView, NetworkRetrieveUpdateDestroyView, ProjectListCreateView, ProjectRetrieveUpdateDestroyView, ProjectStatusView

urlpatterns = [
    path("networks/", NetworkListCreateView.as_view(), name="network-list-create"),
    path("networks/<str:name>/", NetworkRetrieveUpdateDestroyView.as_view(), name="network-retrieve-update-destroy"),
    path("projects/", ProjectListCreateView.as_view(), name="project-list-create"),
    path("projects/<str:name>/", ProjectRetrieveUpdateDestroyView.as_view(), name="project-retrieve-update-destroy"),
    path("projects/<str:project_name>/status/", ProjectStatusView.as_view(), name="project-status"),
] 