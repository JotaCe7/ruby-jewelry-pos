from django.db import models
from django.utils.translation import gettext_lazy as _

from catalogs.models import PaymentMethod
from contacts.models import Customer
from core.models import TimeStampedModel
from inventory.models import Product


class Sale(TimeStampedModel):
    """Ticket header grouping the lines of a single checkout — needed so
    combo/mix-and-match discount proration has a shared scope."""

    date = models.DateField()
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="sales", null=True, blank=True
    )

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"Sale #{self.pk} — {self.date}"


class MovementType(models.TextChoices):
    SALE = "SALE", _("Venta")
    GIFT = "GIFT", _("Regalo / Cortesía")
    DAMAGED = "DAMAGED", _("Dañado / Roto")


class InventoryExit(TimeStampedModel):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="exits")
    movement_type = models.CharField(max_length=10, choices=MovementType.choices)
    quantity = models.PositiveIntegerField()
    # Frozen at sale time — reflects whichever unit price applied (flat
    # suggested_price or a PriceTier), and is never recalculated after.
    unit_price_snapshot = models.DecimalField(max_digits=10, decimal_places=2)
    discount_applied = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # (unit_price_snapshot * quantity) - discount_applied; forced to 0 for
    # GIFT/DAMAGED regardless of discount_applied.
    final_price = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.PROTECT, related_name="exits", null=True, blank=True
    )
    # Shared by every line of the same mix-and-match combo so the discount
    # proration can be traced back; null for standalone lines.
    combo_group = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"Sale #{self.sale_id} — {self.product.sku} x{self.quantity}"
