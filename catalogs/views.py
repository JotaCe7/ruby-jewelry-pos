from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from core.permissions import IsAdminOrReadOnly

from .models import (
    ColorVariant,
    ExpenseCategory,
    PaymentMethod,
    Presentation,
    ProductCategory,
    ProductSubcategory,
)
from .serializers import (
    ColorVariantSerializer,
    ExpenseCategorySerializer,
    PaymentMethodSerializer,
    PresentationSerializer,
    ProductCategorySerializer,
    ProductSubcategorySerializer,
)
from .services import preview_next_category_code, preview_next_subcategory_code


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    # Finance-only concept — a Seller never needs to see expense categories.
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAdminUser]


class PaymentMethodViewSet(viewsets.ModelViewSet):
    # A Seller picks a payment method at checkout, so this needs to stay
    # readable for them, just not editable.
    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsAdminOrReadOnly]


class ProductCategoryViewSet(viewsets.ModelViewSet):
    queryset = ProductCategory.objects.all()
    serializer_class = ProductCategorySerializer
    permission_classes = [IsAdminOrReadOnly]

    @action(detail=False, methods=["get"], permission_classes=[IsAdminUser])
    def preview_code(self, request):
        return Response({"code": preview_next_category_code()})


class ProductSubcategoryViewSet(viewsets.ModelViewSet):
    queryset = ProductSubcategory.objects.select_related("category").all()
    serializer_class = ProductSubcategorySerializer
    filterset_fields = ["category"]
    permission_classes = [IsAdminOrReadOnly]

    @action(detail=False, methods=["get"], permission_classes=[IsAdminUser])
    def preview_code(self, request):
        category_id = request.query_params.get("category")
        if not category_id:
            return Response({"detail": _("category is required.")}, status=400)
        try:
            category = ProductCategory.objects.get(pk=category_id)
        except ProductCategory.DoesNotExist:
            return Response({"detail": _("category not found.")}, status=404)
        return Response({"code": preview_next_subcategory_code(category)})


class ColorVariantViewSet(viewsets.ModelViewSet):
    queryset = ColorVariant.objects.all()
    serializer_class = ColorVariantSerializer
    permission_classes = [IsAdminOrReadOnly]


class PresentationViewSet(viewsets.ModelViewSet):
    queryset = Presentation.objects.all()
    serializer_class = PresentationSerializer
    permission_classes = [IsAdminOrReadOnly]
