from django.contrib import admin

from .models import (
    ColorVariant,
    ExpenseCategory,
    PaymentMethod,
    Presentation,
    ProductCategory,
    ProductSubcategory,
)


@admin.register(ExpenseCategory, ColorVariant, Presentation, ProductCategory)
class NamedCatalogAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "is_cash"]
    list_filter = ["is_active", "is_cash"]
    search_fields = ["name"]


@admin.register(ProductSubcategory)
class ProductSubcategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "is_active"]
    list_filter = ["is_active", "category"]
    search_fields = ["name"]
