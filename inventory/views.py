from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from catalogs.models import ProductSubcategory
from core.permissions import IsAdminOrReadOnly

from .filters import ProductFilter
from .models import InventoryAudit, InventoryDamage, InventoryEntry, PackPrice, PriceTier, Product
from .serializers import (
    InventoryAuditSerializer,
    InventoryDamageSerializer,
    InventoryEntrySerializer,
    PackPriceSerializer,
    PriceTierCopySerializer,
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
            .select_related("subcategory__category", "color", "presentation", "supplier", "pack_price")
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
    # Pricing strategy is Admin-only. It's already exposed read-only to
    # everyone nested inside ProductSerializer.price_tiers.
    queryset = PriceTier.objects.all()
    serializer_class = PriceTierSerializer
    filterset_fields = ["product"]
    permission_classes = [IsAdminUser]

    @action(detail=False, methods=["post"])
    def copy(self, request):
        # Replaces (not merges) each target's tier set with the source's,
        # so reverting a temporary price change is just copying the
        # normal set back over the same targets.
        serializer = PriceTierCopySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        source = serializer.validated_data["source_product"]
        targets = [
            product for product in serializer.validated_data["target_products"] if product.pk != source.pk
        ]
        tiers = list(source.price_tiers.values("min_quantity", "unit_price"))
        with transaction.atomic():
            PriceTier.objects.filter(product__in=targets).delete()
            PriceTier.objects.bulk_create(
                PriceTier(product=target, min_quantity=tier["min_quantity"], unit_price=tier["unit_price"])
                for target in targets
                for tier in tiers
            )
        return Response(status=204)


class PackPriceViewSet(viewsets.ModelViewSet):
    # Pricing strategy is Admin-only. It's already exposed read-only to
    # everyone nested inside ProductSerializer.pack_price.
    queryset = PackPrice.objects.all()
    serializer_class = PackPriceSerializer
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
