from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/catalogs/", include("catalogs.urls")),
    path("api/contacts/", include("contacts.urls")),
    path("api/finance/", include("finance.urls")),
    path("api/inventory/", include("inventory.urls")),
    path("api/pos/", include("pos.urls")),
    path("api/dashboard/", include("dashboard.urls")),
]
