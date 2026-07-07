from django.db import models
from django.utils.translation import gettext_lazy as _


class DailyExchangeRate(models.Model):
    """Local cache of the USD/PEN SUNAT rate, keyed by date.

    Avoids re-hitting the upstream API (which rate-limits aggressively
    without an API key) for a date that has already been looked up once.
    """

    date = models.DateField(unique=True)
    value = models.DecimalField(max_digits=10, decimal_places=4)
    source = models.CharField(max_length=100, default="SUNAT")
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("daily exchange rate")
        verbose_name_plural = _("daily exchange rates")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} — {self.value}"
