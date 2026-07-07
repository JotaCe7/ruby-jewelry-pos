from rest_framework import viewsets

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
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer


class PaymentMethodViewSet(viewsets.ModelViewSet):
    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer


class ProductCategoryViewSet(viewsets.ModelViewSet):
    queryset = ProductCategory.objects.all()
    serializer_class = ProductCategorySerializer


class ProductSubcategoryViewSet(viewsets.ModelViewSet):
    queryset = ProductSubcategory.objects.select_related("category").all()
    serializer_class = ProductSubcategorySerializer
    filterset_fields = ["category"]


class ColorVariantViewSet(viewsets.ModelViewSet):
    queryset = ColorVariant.objects.all()
    serializer_class = ColorVariantSerializer


class PresentationViewSet(viewsets.ModelViewSet):
    queryset = Presentation.objects.all()
    serializer_class = PresentationSerializer
