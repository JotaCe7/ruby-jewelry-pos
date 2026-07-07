from django.contrib import admin

from .models import DailyExchangeRate


@admin.register(DailyExchangeRate)
class DailyExchangeRateAdmin(admin.ModelAdmin):
    list_display = ["date", "value", "source", "fetched_at"]
    list_filter = ["source"]
    ordering = ["-date"]
