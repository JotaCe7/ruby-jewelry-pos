from rest_framework.routers import DefaultRouter

from .views import CustomerViewSet, SupplierViewSet

app_name = "contacts"

router = DefaultRouter()
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("customers", CustomerViewSet, basename="customer")

urlpatterns = router.urls
