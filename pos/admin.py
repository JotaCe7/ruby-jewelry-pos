from django.contrib import admin

from .models import InventoryExit, Sale


class InventoryExitInline(admin.TabularInline):
    model = InventoryExit
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ["id", "date", "customer"]
    list_filter = ["customer"]
    date_hierarchy = "date"
    inlines = [InventoryExitInline]


@admin.register(InventoryExit)
class InventoryExitAdmin(admin.ModelAdmin):
    list_display = ["sale", "product", "movement_type", "quantity", "final_price", "combo_group"]
    list_filter = ["movement_type"]
