from django.contrib import admin

from .models import InventoryAudit, InventoryEntry, PriceTier, Product


class PriceTierInline(admin.TabularInline):
    model = PriceTier
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        "sku",
        "base_model",
        "subcategory",
        "supplier",
        "unit_cost",
        "suggested_price",
        "min_stock",
        "is_active",
    ]
    list_filter = ["is_active", "subcategory__category", "subcategory", "supplier"]
    search_fields = ["sku", "base_model"]
    inlines = [PriceTierInline]


@admin.register(InventoryEntry)
class InventoryEntryAdmin(admin.ModelAdmin):
    list_display = ["date", "product", "quantity", "unit_cost"]
    list_filter = ["product"]
    date_hierarchy = "date"


@admin.register(InventoryAudit)
class InventoryAuditAdmin(admin.ModelAdmin):
    list_display = [
        "date",
        "product",
        "theoretical_stock_snapshot",
        "physical_count",
        "loss_adjustment",
        "loss_value",
    ]
    list_filter = ["product"]
    date_hierarchy = "date"
