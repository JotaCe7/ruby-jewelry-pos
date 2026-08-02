from rest_framework.routers import DefaultRouter

from .views import UserAccountViewSet

app_name = "core"

router = DefaultRouter()
router.register("users", UserAccountViewSet, basename="user-account")

urlpatterns = router.urls
