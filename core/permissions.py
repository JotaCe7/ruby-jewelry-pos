from rest_framework import permissions


class IsAdminOrReadOnly(permissions.BasePermission):
    """Any authenticated user (Admin or Vendedor) can read; only Admin
    (Django's is_staff) can create/update/delete. Used for config catalogs
    and directory data the POS needs to read but never edit at the register.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user.is_staff)
