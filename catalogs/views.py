from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser

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


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    # Finance-only concept — a Vendedor never needs to see expense categories.
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAdminUser]


class PaymentMethodViewSet(viewsets.ModelViewSet):
    # A Vendedor picks a payment method at checkout, so this needs to stay
    # readable for them, just not editable.
    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsAdminOrReadOnly]


class ProductCategoryViewSet(viewsets.ModelViewSet):
    queryset = ProductCategory.objects.all()
    serializer_class = ProductCategorySerializer
    permission_classes = [IsAdminOrReadOnly]


class ProductSubcategoryViewSet(viewsets.ModelViewSet):
    queryset = ProductSubcategory.objects.select_related("category").all()
    serializer_class = ProductSubcategorySerializer
    filterset_fields = ["category"]
    permission_classes = [IsAdminOrReadOnly]


class ColorVariantViewSet(viewsets.ModelViewSet):
    queryset = ColorVariant.objects.all()
    serializer_class = ColorVariantSerializer
    permission_classes = [IsAdminOrReadOnly]


class PresentationViewSet(viewsets.ModelViewSet):
    queryset = Presentation.objects.all()
    serializer_class = PresentationSerializer
    permission_classes = [IsAdminOrReadOnly]
