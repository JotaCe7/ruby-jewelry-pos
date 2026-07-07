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
        fields = ["id", "name", "is_active", "is_cash"]


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ["id", "name", "is_active"]


class ProductSubcategorySerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = ProductSubcategory
        fields = ["id", "name", "category", "category_name", "is_active"]


class ColorVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ColorVariant
        fields = ["id", "name", "is_active"]


class PresentationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Presentation
        fields = ["id", "name", "is_active"]
