from django.contrib import admin

from .models import Expense


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = [
        "date",
        "category",
        "description",
        "original_amount",
        "currency",
        "pen_equivalent_amount",
        "payment_method",
    ]
    list_filter = ["category", "currency", "payment_method"]
    search_fields = ["description"]
    date_hierarchy = "date"
