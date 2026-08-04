from django.db import models
from django.utils.translation import gettext_lazy as _

from catalogs.models import ExpenseCategory, PaymentMethod
from contacts.models import Supplier
from core.models import TimeStampedModel


class ReceiptType(models.TextChoices):
    BOLETA = "BOLETA", _("Simplified receipt")
    FACTURA = "FACTURA", _("Invoice")
    RECIBO = "RECIBO", _("Voucher")
    NONE = "NONE", _("None")


class PaymentStatus(models.TextChoices):
    PREPAID = "PREPAID", _("Prepaid")
    CASH_ON_ORDER = "CASH_ON_ORDER", _("Cash on order")
    INSTALLMENTS = "INSTALLMENTS", _("In installments")
    CASH_ON_DELIVERY = "CASH_ON_DELIVERY", _("Cash on delivery")


class Currency(models.TextChoices):
    PEN = "PEN", _("Soles (PEN)")
    USD = "USD", _("US Dollars (USD)")


class Expense(TimeStampedModel):
    date = models.DateField()
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    description = models.TextField()
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="expenses", null=True, blank=True
    )
    receipt_type = models.CharField(
        max_length=20, choices=ReceiptType.choices, default=ReceiptType.NONE
    )
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices)
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.PROTECT, related_name="expenses"
    )
    payment_reference = models.CharField(max_length=100, blank=True)
    original_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.PEN)
    # Frozen at creation time via ExchangeRateService — never recalculated
    # afterwards, even if that date's cached rate is later corrected.
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4)
    pen_equivalent_amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.date} — {self.description[:40]}"
