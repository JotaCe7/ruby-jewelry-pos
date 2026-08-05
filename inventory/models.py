from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _

from catalogs.models import ColorVariant, Presentation, ProductSubcategory
from contacts.models import Supplier
from core.models import TimeStampedModel


class ProductQuerySet(models.QuerySet):
    def with_stock(self):
        """Annotates current_stock from historical entries, minus audit
        shrinkage, damage reports, and POS exits. Uses independent
        Subqueries (not multiple Sum()s on sibling reverse relations in one
        annotate()): combining them directly would JOIN entries × audits ×
        damages × exits and inflate each sum by the other tables' row
        counts. Keep in sync with `inventory.services.get_current_stock`,
        which does the same computation for single-instance use (e.g. right
        after saving a new entry, before the queryset would reflect it in a
        fresh query).
        """
        # Imported lazily to avoid a circular import: pos.models.InventoryExit
        # has a FK to Product, so pos can't be imported at module load time.
        from pos.models import InventoryExit

        entries_total = (
            InventoryEntry.objects.filter(product=OuterRef("pk"))
            .order_by()
            .values("product")
            .annotate(total=Sum("quantity"))
            .values("total")
        )
        audit_loss_total = (
            InventoryAudit.objects.filter(product=OuterRef("pk"))
            .order_by()
            .values("product")
            .annotate(total=Sum("loss_adjustment"))
            .values("total")
        )
        damages_total = (
            InventoryDamage.objects.filter(product=OuterRef("pk"))
            .order_by()
            .values("product")
            .annotate(total=Sum("quantity"))
            .values("total")
        )
        exits_total = (
            InventoryExit.objects.filter(product=OuterRef("pk"))
            .order_by()
            .values("product")
            .annotate(total=Sum("quantity"))
            .values("total")
        )
        return self.annotate(
            current_stock=Coalesce(Subquery(entries_total, output_field=IntegerField()), 0)
            - Coalesce(Subquery(audit_loss_total, output_field=IntegerField()), 0)
            - Coalesce(Subquery(damages_total, output_field=IntegerField()), 0)
            - Coalesce(Subquery(exits_total, output_field=IntegerField()), 0)
        )


class BarcodeSequence(models.Model):
    """Singleton row (always pk=1) tracking the next sequential number for
    auto-generated Product barcodes (see inventory.services.generate_barcode
    for the full EAN-13 construction). Locked via select_for_update before
    allocating, mirroring pos.models.DocumentSeries' sequence-number pattern."""

    next_value = models.PositiveIntegerField(default=1)

    @classmethod
    def get_or_create_singleton(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"next: {self.next_value}"


class Product(TimeStampedModel):
    # Auto-generated as the parent subcategory's code + a 3-digit
    # sequential number scoped to that subcategory (e.g. "0101001",
    # "0101002" under subcategory "0101"). Never editable afterward. The
    # field name stays `sku` since it's referenced throughout
    # pos/dashboard/inventory, even though it holds this hierarchical
    # code rather than an abbreviation-based value (e.g. "ARE-FAN").
    # editable=False also makes DRF's ModelSerializer expose this
    # read-only automatically.
    sku = models.CharField(max_length=50, unique=True, editable=False, blank=True)
    # Auto-generated (see inventory.services.generate_barcode) but editable,
    # e.g. if a supplier's own barcode should be used instead. Validated
    # for uniqueness the same way sku is (ProductSerializer.validate_barcode).
    barcode = models.CharField(max_length=13, unique=True)
    base_model = models.CharField(max_length=150)
    image = models.ImageField(upload_to="products/", null=True, blank=True)
    subcategory = models.ForeignKey(
        ProductSubcategory, on_delete=models.PROTECT, related_name="products"
    )
    color = models.ForeignKey(
        ColorVariant, on_delete=models.PROTECT, related_name="products", null=True, blank=True
    )
    presentation = models.ForeignKey(
        Presentation, on_delete=models.PROTECT, related_name="products", null=True, blank=True
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="products", null=True, blank=True
    )
    # Running weighted-average cost, updated by InventoryEntry.unit_cost.
    # Never edited directly (see inventory.services.apply_stock_entry_cost).
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    suggested_price = models.DecimalField(max_digits=10, decimal_places=2)
    min_stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["base_model"]

    def __str__(self):
        return f"{self.sku} ({self.base_model})"

    def save(self, *args, **kwargs):
        if not self.pk and not self.sku:
            with transaction.atomic():
                subcategory = ProductSubcategory.objects.select_for_update().get(
                    pk=self.subcategory_id
                )
                # MAX-based, not count()-based: a deleted sibling must
                # never free up its number for reuse.
                existing_suffixes = [
                    int(code[len(subcategory.code) :])
                    for code in Product.objects.filter(subcategory=subcategory).values_list(
                        "sku", flat=True
                    )
                    if code
                ]
                next_suffix = max(existing_suffixes, default=0) + 1
                self.sku = subcategory.code + str(next_suffix).zfill(3)
        super().save(*args, **kwargs)


class PriceTier(TimeStampedModel):
    """A quantity breakpoint below which the flat `suggested_price` applies
    (min_quantity starts at 2, since the qty=1 case is just suggested_price)."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="price_tiers")
    min_quantity = models.PositiveIntegerField(validators=[MinValueValidator(2)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["min_quantity"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "min_quantity"], name="unique_tier_per_product_quantity"
            )
        ]

    def __str__(self):
        return f"{self.product.sku} ({self.min_quantity}+: {self.unit_price})"


class InventoryEntry(TimeStampedModel):
    """The physical 'unpacking' record. `unit_cost` is optional: when given,
    it updates the product's running weighted-average cost; when omitted,
    this is a purely physical stock movement (e.g. splitting an assorted
    bag into SKUs whose financial cost was already booked as an Expense)."""

    date = models.DateField()
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="entries")
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name_plural = _("inventory entries")

    def __str__(self):
        return f"{self.date}: {self.product.sku} (+{self.quantity})"


class InventoryAudit(TimeStampedModel):
    date = models.DateField()
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="audits")
    physical_count = models.IntegerField()
    # Snapshot of what the system expected before this audit's correction,
    # and the resulting deltas. Frozen at creation, never recalculated.
    theoretical_stock_snapshot = models.IntegerField()
    loss_adjustment = models.IntegerField()
    loss_value = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.date}: {self.product.sku} (ajuste {self.loss_adjustment})"


class InventoryDamage(TimeStampedModel):
    """A single known, direct loss (a piece broke or was scratched beyond
    sale, etc.). Distinct from InventoryAudit's periodic count
    reconciliation, and never tied to a Sale/ticket. Subtracts from stock
    on its own, the same way audit shrinkage does."""

    date = models.DateField()
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="damages")
    quantity = models.PositiveIntegerField(default=1)
    # Frozen at report time. A loss is valued at what the unit actually
    # cost the business then, not at today's average cost.
    unit_cost_snapshot = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=255, blank=True)
    # Who is responsible for the piece (not necessarily whoever is typing
    # this into the system): a system user when there is one, otherwise
    # free text (e.g. a cleaning contractor with no account here).
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="+", null=True, blank=True
    )
    responsible_other = models.CharField(max_length=150, blank=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reported_damages"
    )

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = _("inventory damage report")
        verbose_name_plural = _("inventory damage reports")

    def __str__(self):
        return f"{self.date}: {self.product.sku} (-{self.quantity})"
