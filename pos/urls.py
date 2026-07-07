from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import DraftSaleFinalizeView, DraftSaleView, SaleViewSet

app_name = "pos"

router = DefaultRouter()
router.register("sales", SaleViewSet, basename="sale")

urlpatterns = [
    path("draft/", DraftSaleView.as_view(), name="draft"),
    path("draft/finalize/", DraftSaleFinalizeView.as_view(), name="draft-finalize"),
] + router.urls
