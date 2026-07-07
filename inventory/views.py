from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from catalogs.models import ColorVariant, Presentation

from .filters import ProductFilter
from .models import InventoryAudit, InventoryEntry, PriceTier, Product
from .serializers import (
    InventoryAuditSerializer,
    InventoryEntrySerializer,
    PriceTierSerializer,
    ProductSerializer,
)
from .services import generate_sku, get_unique_sku


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    filterset_class = ProductFilter
    ordering_fields = ["base_model", "suggested_price", "current_stock", "unit_cost"]
    ordering = ["base_model"]

    def get_queryset(self):
        return (
            Product.objects.with_stock()
            .select_related("subcategory__category", "color", "presentation", "supplier")
            .prefetch_related("price_tiers")
        )


class PriceTierViewSet(viewsets.ModelViewSet):
    queryset = PriceTier.objects.all()
    serializer_class = PriceTierSerializer
    filterset_fields = ["product"]


class InventoryEntryViewSet(viewsets.ModelViewSet):
    queryset = InventoryEntry.objects.select_related("product").all()
    serializer_class = InventoryEntrySerializer
    filterset_fields = ["product"]


class InventoryAuditViewSet(viewsets.ModelViewSet):
    queryset = InventoryAudit.objects.select_related("product").all()
    serializer_class = InventoryAuditSerializer
    filterset_fields = ["product"]


class SkuPreviewView(APIView):
    def get(self, request):
        base_model = request.query_params.get("base_model", "")
        color_id = request.query_params.get("color")
        presentation_id = request.query_params.get("presentation")

        if not base_model:
            return Response({"detail": "base_model is required."}, status=400)

        color_name = ColorVariant.objects.filter(pk=color_id).values_list("name", flat=True).first() or ""
        presentation_name = (
            Presentation.objects.filter(pk=presentation_id).values_list("name", flat=True).first() or ""
        )

        base_sku = generate_sku(base_model, color_name, presentation_name)
        return Response({"sku": get_unique_sku(base_sku)})
