from django.contrib import admin

from .models import Customer, Supplier


@admin.register(Supplier, Customer)
class ContactAdmin(admin.ModelAdmin):
    list_display = ["name", "tax_id", "phone", "email", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "tax_id", "email"]
