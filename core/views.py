from rest_framework.response import Response
from rest_framework.views import APIView


class CurrentUserView(APIView):
    """Tells the frontend who's logged in and their role, so it can show
    the Admin nav/screens or the stripped-down Vendedor-only POS view."""

    def get(self, request):
        user = request.user
        return Response(
            {
                "username": user.username,
                "is_admin": user.is_staff,
            }
        )
