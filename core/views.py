from django.contrib.auth import get_user_model
from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import UserSerializer

User = get_user_model()


class CurrentUserView(APIView):
    """Tells the frontend who's logged in and their role, so it can show
    the Admin nav/screens or the stripped-down Vendedor-only POS view."""

    def get(self, request):
        user = request.user
        return Response(
            {
                "id": user.id,
                "username": user.username,
                "is_admin": user.is_staff,
            }
        )


class UserListView(APIView):
    """Admin-only: bare id/username list, used to power seller-selection
    dropdowns (force-open a register, retroactive sale attribution, closing
    another seller's register on their behalf)."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        users = User.objects.filter(is_active=True).order_by("username")
        return Response([{"id": u.id, "username": u.username, "is_admin": u.is_staff} for u in users])


class UserAccountViewSet(viewsets.ModelViewSet):
    """Full user management (Admin only): list/create/edit, including the
    profile fields this business wants on file (phone, birth date, etc).
    Distinct from UserListView above — that one is a lightweight
    active-only list for seller-selection dropdowns and stays untouched.
    Never hard-deletes — DELETE isn't exposed at all; deactivate via
    PATCH {"is_active": false} instead, matching this project's
    soft-disable convention everywhere else (never break the historical
    FK from past sales/closings to a removed user)."""

    http_method_names = ["get", "post", "patch", "head", "options"]
    queryset = User.objects.select_related("profile").order_by("username")
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]
