from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from catalogs.models import ProductSubcategory
from core.permissions import IsAdminOrReadOnly

from .filters import ProductFilter
from .models import InventoryAudit, InventoryDamage, InventoryEntry, PriceTier, Product
from .serializers import (
    InventoryAuditSerializer,
    InventoryDamageSerializer,
    InventoryEntrySerializer,
    PriceTierSerializer,
    ProductSerializer,
)
from .services import preview_next_product_code


class ProductViewSet(viewsets.ModelViewSet):
    # A Seller needs to browse the catalog (stock/price) from the POS
    # picker, but only Admin edits products.
    serializer_class = ProductSerializer
    filterset_class = ProductFilter
    ordering_fields = ["base_model", "suggested_price", "current_stock", "unit_cost"]
    ordering = ["base_model"]
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        return (
            Product.objects.with_stock()
            .select_related("subcategory__category", "color", "presentation", "supplier")
            .prefetch_related("price_tiers")
        )

    @action(detail=False, methods=["get"], permission_classes=[IsAdminUser])
    def preview_code(self, request):
        subcategory_id = request.query_params.get("subcategory")
        if not subcategory_id:
            return Response({"detail": _("subcategory is required.")}, status=400)
        try:
            subcategory = ProductSubcategory.objects.get(pk=subcategory_id)
        except ProductSubcategory.DoesNotExist:
            return Response({"detail": _("subcategory not found.")}, status=404)
        return Response({"code": preview_next_product_code(subcategory)})


class PriceTierViewSet(viewsets.ModelViewSet):
    # Pricing strategy — Admin-only; already exposed read-only to everyone
    # nested inside ProductSerializer.price_tiers.
    queryset = PriceTier.objects.all()
    serializer_class = PriceTierSerializer
    filterset_fields = ["product"]
    permission_classes = [IsAdminUser]


class InventoryEntryViewSet(viewsets.ModelViewSet):
    queryset = InventoryEntry.objects.select_related("product").all()
    serializer_class = InventoryEntrySerializer
    filterset_fields = ["product"]
    permission_classes = [IsAdminUser]


class InventoryAuditViewSet(viewsets.ModelViewSet):
    queryset = InventoryAudit.objects.select_related("product").all()
    serializer_class = InventoryAuditSerializer
    filterset_fields = ["product"]
    permission_classes = [IsAdminUser]


class InventoryDamageViewSet(viewsets.ModelViewSet):
    queryset = InventoryDamage.objects.select_related("product", "responsible", "reported_by").all()
    serializer_class = InventoryDamageSerializer
    filterset_fields = ["product"]
    permission_classes = [IsAdminUser]
