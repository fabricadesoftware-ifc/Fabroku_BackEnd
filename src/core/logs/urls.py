from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AppLogViewSet

router = DefaultRouter()
router.register(r'', AppLogViewSet, basename='logs')

urlpatterns = [
    path('', include(router.urls)),
]
