from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from catalogs.models import PaymentMethod
from contacts.models import Customer
from core.models import TimeStampedModel
from inventory.models import Product


class MovementType(models.TextChoices):
    SALE = "SALE", _("Venta")
    GIFT = "GIFT", _("Regalo / Cortesía")
    DAMAGED = "DAMAGED", _("Dañado / Roto")


class Sale(TimeStampedModel):
    """Ticket header grouping the lines of a single checkout — needed so
    combo/mix-and-match discount proration has a shared scope."""

    date = models.DateField()
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="sales", null=True, blank=True
    )
    # Whoever was logged in when the sale was finalized — enables daily
    # per-seller closing reports.
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales", null=True, blank=True
    )

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"Sale #{self.pk} — {self.date}"


class InventoryExit(TimeStampedModel):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="exits")
    movement_type = models.CharField(max_length=10, choices=MovementType.choices)
    quantity = models.PositiveIntegerField()
    # Frozen at sale time — reflects whichever unit price applied (flat
    # suggested_price or a PriceTier), and is never recalculated after.
    unit_price_snapshot = models.DecimalField(max_digits=10, decimal_places=2)
    # Frozen at sale time too — so a GIFT/DAMAGED loss is valued at what the
    # unit actually cost the business then, not at today's average cost.
    unit_cost_snapshot = models.DecimalField(max_digits=10, decimal_places=2, default=0)
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


class DraftSale(TimeStampedModel):
    """Server-persisted in-progress ticket — one per user, survives a dead
    phone or switching devices mid-sale (unlike a client-only localStorage
    draft). Never touches stock/InventoryExit; only `finalize` (in
    pos/services.py) promotes it into a real Sale, using the exact same
    combo proration logic as a direct Sale creation would."""

    created_by = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="draft_sale"
    )
    date = models.DateField()
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, related_name="draft_sales", null=True, blank=True
    )

    def __str__(self):
        return f"Draft — {self.created_by}"


class DraftSaleLine(TimeStampedModel):
    draft_sale = models.ForeignKey(DraftSale, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="draft_lines")
    movement_type = models.CharField(
        max_length=10, choices=MovementType.choices, default=MovementType.SALE
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.SET_NULL, related_name="draft_lines", null=True, blank=True
    )
    # Same grouping convention as the SaleLineInputSerializer payload: a
    # client-chosen label shared by every line of one combo, plus the
    # combo's shared discount total repeated on each of those lines.
    combo_key = models.CharField(max_length=50, blank=True)
    combo_discount_total = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.draft_sale_id} — {self.product.sku} x{self.quantity}"


class ProcessDate(models.Model):
    """Singleton: the shop's single official business date — never one per
    seller. A Sale is always dated to whatever this is at creation time,
    not to a client-supplied date. Advances automatically (see
    pos/services.py) once every seller who had a session open for the
    current date has closed it with a Z; an Admin can also set it directly
    (e.g. to attribute a forgotten sale to an already-closed date)."""

    current_date = models.DateField()

    @classmethod
    def get_or_create_default(cls):
        obj, _created = cls.objects.get_or_create(pk=1, defaults={"current_date": timezone.localdate()})
        return obj

    def __str__(self):
        return str(self.current_date)


class CashRegisterSession(TimeStampedModel):
    """Whether this user (seller or admin acting as one) currently has
    their register open. No process_date of its own — there is only ever
    one, global (ProcessDate)."""

    seller = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="register_session"
    )
    is_open = models.BooleanField(default=False)
    opened_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.seller} — {'abierta' if self.is_open else 'cerrada'}"


class ClosingPin(models.Model):
    """Singleton: the shared PIN required to authorize any X/Z closing
    (both Pantalla-preview and Impresora-real modes) — deliberately not
    tied to any single user's login password, so it survives account
    changes and isn't the same secret as anyone's login."""

    pin_hash = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get_or_create_default(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj

    def set_pin(self, raw_pin: str):
        self.pin_hash = make_password(raw_pin)
        self.save(update_fields=["pin_hash"])

    def check_pin(self, raw_pin: str) -> bool:
        return bool(self.pin_hash) and check_password(raw_pin, self.pin_hash)


class ClosingType(models.TextChoices):
    X = "X", _("Cierre X (parcial)")
    Z = "Z", _("Cierre Z (final del día)")


class RegisterClosing(TimeStampedModel):
    """One row per executed (Impresora-mode) X or Z closing. A Pantalla
    preview never creates one of these — nothing is persisted or changed
    until the closing is actually run for real."""

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="register_closings"
    )
    closing_type = models.CharField(max_length=1, choices=ClosingType.choices)
    process_date = models.DateField()
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    total_sales = models.DecimalField(max_digits=12, decimal_places=2)
    total_by_payment_method = models.JSONField(default=dict)
    total_losses = models.DecimalField(max_digits=12, decimal_places=2)
    sale_count = models.PositiveIntegerField()
    # Usually == seller (self-service, the normal case); differs only when
    # an Admin runs this closing on the seller's behalf — see
    # pos/services.py for the one scenario where that happens.
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="closings_performed"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_closing_type_display()} — {self.seller} — {self.process_date}"
