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
    # Set only via void_document() voiding this sale's Nota de Venta — never
    # edited directly. A voided sale's lines are kept for the audit trail
    # (stock is restored via a compensating InventoryEntry, not by deleting
    # these rows), but every revenue aggregation (closings, dashboard) must
    # exclude it.
    is_voided = models.BooleanField(default=False)

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


class AdminPin(models.Model):
    """One PIN per admin — deliberately not tied to that admin's login
    password, so it survives account changes and isn't the same secret as
    their login. Any admin's PIN authorizes an X/Z closing or an
    anulación (find_by_pin checks every admin's hash), but a Cierre Z
    additionally records *which* admin's PIN matched as its
    `authorized_by` — the whole reason this moved from one shared PIN to
    one per admin."""

    admin = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="closing_pin"
    )
    pin_hash = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get_or_create_for(cls, admin):
        obj, _created = cls.objects.get_or_create(admin=admin)
        return obj

    @classmethod
    def find_by_pin(cls, raw_pin: str):
        """Returns the admin whose PIN matches `raw_pin`, or None. Checking
        every admin's hash in turn is fine at this shop's staff-count
        scale."""
        if not raw_pin:
            return None
        for admin_pin in cls.objects.exclude(pin_hash="").select_related("admin"):
            if check_password(raw_pin, admin_pin.pin_hash):
                return admin_pin.admin
        return None

    def set_pin(self, raw_pin: str):
        self.pin_hash = make_password(raw_pin)
        self.save(update_fields=["pin_hash"])


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
    # Which admin's PIN authorized this closing — only ever set for a Z
    # (an X doesn't need this level of sign-off). Distinct from
    # performed_by: performed_by is whoever ran the closing (could be the
    # seller themselves), authorized_by is the admin whose personal PIN
    # was matched to confirm it.
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="closings_authorized",
    )
    # Per (document_type, series): first/last correlativo issued in the
    # period, how many, and their combined amount (voided documents keep
    # their correlativo in the first/last range but don't count toward
    # amount — same "excluded from revenue" rule as everywhere else).
    # Each item: {document_type, document_type_display, series,
    # first_number, last_number, count, amount}.
    document_breakdown = models.JSONField(default=list)
    # Per ProductCategory: {category_id, category_name, quantity, amount}.
    category_breakdown = models.JSONField(default=list)
    # Per Product — opt-in at closing time (adds paper), so null means
    # "not requested" rather than "empty": {product_id, sku, base_model,
    # quantity, amount}.
    product_breakdown = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_closing_type_display()} — {self.seller} — {self.process_date}"


class DocumentType(models.TextChoices):
    """Only NOTA_VENTA is actually issuable today (internal control, not a
    SUNAT-valid fiscal document). The rest exist so wiring up real
    electronic invoicing later — Boleta/Factura via a PSE like Nubefact,
    and Nota de Crédito/Débito to adjust an already-issued document — is a
    services/views change, not a schema migration."""

    NOTA_VENTA = "NOTA_VENTA", _("Nota de Venta")
    BOLETA = "BOLETA", _("Boleta de Venta")
    FACTURA = "FACTURA", _("Factura")
    NOTA_CREDITO = "NOTA_CREDITO", _("Nota de Crédito")
    NOTA_DEBITO = "NOTA_DEBITO", _("Nota de Débito")


class DocumentStatus(models.TextChoices):
    ISSUED = "ISSUED", _("Emitido")
    VOIDED = "VOIDED", _("Anulado")


DEFAULT_DOCUMENT_SERIES = {
    DocumentType.NOTA_VENTA: "NV01",
    DocumentType.BOLETA: "B001",
    DocumentType.FACTURA: "F001",
    DocumentType.NOTA_CREDITO: "NC01",
    DocumentType.NOTA_DEBITO: "ND01",
}


class DocumentSeries(models.Model):
    """One row per document type — tracks the next correlativo so numbers
    are gapless and never reused. `issue_document` locks this row
    (select_for_update) before allocating a number, so two concurrent
    sales can never receive the same one."""

    document_type = models.CharField(max_length=15, choices=DocumentType.choices, unique=True)
    series = models.CharField(max_length=10)
    next_correlativo = models.PositiveIntegerField(default=1)

    @classmethod
    def get_or_create_default(cls, document_type):
        obj, _created = cls.objects.get_or_create(
            document_type=document_type,
            defaults={"series": DEFAULT_DOCUMENT_SERIES[document_type]},
        )
        return obj

    def __str__(self):
        return f"{self.series} (next: {self.next_correlativo})"


class SaleDocument(TimeStampedModel):
    """The printable, sequentially-numbered comprobante for a Sale. Customer
    identity is snapshotted at issuance so a later edit to the Customer
    record never changes what was actually printed. `related_document` is
    for a future Nota de Crédito/Débito, which always references the
    document it adjusts — null for a standalone Nota de Venta/Boleta/
    Factura."""

    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="documents")
    document_type = models.CharField(max_length=15, choices=DocumentType.choices)
    series = models.CharField(max_length=10)
    correlativo = models.PositiveIntegerField()
    status = models.CharField(
        max_length=10, choices=DocumentStatus.choices, default=DocumentStatus.ISSUED
    )

    customer_name = models.CharField(max_length=150, blank=True)
    customer_document_type = models.CharField(max_length=20, blank=True)
    customer_document_number = models.CharField(max_length=20, blank=True)

    # Prices are IGV-inclusive; subtotal/tax_amount are derived backward from
    # `total` at issuance time (see pos/services.py:issue_document) and
    # frozen from then on.
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    related_document = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="adjustments"
    )

    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documents_voided",
    )
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["series", "correlativo"], name="unique_series_correlativo")
        ]

    def __str__(self):
        return f"{self.series}-{self.correlativo:06d}"
