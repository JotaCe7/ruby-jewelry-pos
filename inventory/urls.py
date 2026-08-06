from rest_framework.routers import DefaultRouter

from .views import (
    InventoryAuditViewSet,
    InventoryDamageViewSet,
    InventoryEntryViewSet,
    PackPriceViewSet,
    PriceTierViewSet,
    ProductViewSet,
)

app_name = "inventory"

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")
router.register("price-tiers", PriceTierViewSet, basename="price-tier")
router.register("pack-prices", PackPriceViewSet, basename="pack-price")
router.register("entries", InventoryEntryViewSet, basename="entry")
router.register("audits", InventoryAuditViewSet, basename="audit")
router.register("damages", InventoryDamageViewSet, basename="damage")

urlpatterns = router.urls
