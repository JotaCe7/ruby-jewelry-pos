from django.contrib import admin

from .models import DraftSale, DraftSaleLine, InventoryExit, Sale


class InventoryExitInline(admin.TabularInline):
    model = InventoryExit
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ["id", "date", "customer", "seller"]
    list_filter = ["customer", "seller"]
    date_hierarchy = "date"
    inlines = [InventoryExitInline]


@admin.register(InventoryExit)
class InventoryExitAdmin(admin.ModelAdmin):
    list_display = ["sale", "product", "movement_type", "quantity", "final_price", "combo_group"]
    list_filter = ["movement_type"]


class DraftSaleLineInline(admin.TabularInline):
    model = DraftSaleLine
    extra = 0


@admin.register(DraftSale)
class DraftSaleAdmin(admin.ModelAdmin):
    list_display = ["created_by", "date", "customer", "updated_at"]
    inlines = [DraftSaleLineInline]
