from rest_framework import serializers

from .models import (
    ColorVariant,
    ExpenseCategory,
    PaymentMethod,
    Presentation,
    ProductCategory,
    ProductSubcategory,
)


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "name", "is_active"]


class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = ["id", "name", "is_active", "is_cash", "is_default"]


class ProductCategorySerializer(serializers.ModelSerializer):
    # code is read-only (ProductCategory.editable=False) — save() assigns
    # it as an auto-incrementing 2-digit sequence, never user input.
    class Meta:
        model = ProductCategory
        fields = ["id", "code", "name", "is_active", "image"]


class ProductSubcategorySerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    # code is read-only (ProductSubcategory.editable=False) — save()
    # assigns it as the parent category's code + a sequence scoped to
    # that category, never user input.
    class Meta:
        model = ProductSubcategory
        fields = ["id", "code", "name", "category", "category_name", "is_active", "image"]


class ColorVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ColorVariant
        fields = ["id", "name", "is_active"]


class PresentationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Presentation
        fields = ["id", "name", "is_active"]
