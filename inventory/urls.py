from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    InventoryAuditViewSet,
    InventoryEntryViewSet,
    PriceTierViewSet,
    ProductViewSet,
    SkuPreviewView,
)

app_name = "inventory"

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")
router.register("price-tiers", PriceTierViewSet, basename="price-tier")
router.register("entries", InventoryEntryViewSet, basename="entry")
router.register("audits", InventoryAuditViewSet, basename="audit")

urlpatterns = [
    path("products/preview-sku/", SkuPreviewView.as_view(), name="preview-sku"),
] + router.urls
