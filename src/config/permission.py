from rest_framework.permissions import SAFE_METHODS, BasePermission


class CustomUserPermission(BasePermission):

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS and request.user.is_authenticated:
            return True
        return request.user and request.user.is_authenticated and request.user.is_staff
