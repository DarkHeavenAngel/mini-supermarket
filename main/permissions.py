from rest_framework.permissions import BasePermission

class IsManager(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.empl_role == "Менеджер"

class IsCashier(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.empl_role == "Касир"

