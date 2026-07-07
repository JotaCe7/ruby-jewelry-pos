from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _

from catalogs.models import ColorVariant, Presentation, ProductSubcategory
from contacts.models import Supplier
from core.models import TimeStampedModel


class ProductQuerySet(models.QuerySet):
    def with_stock(self):
        """Annotates current_stock from historical entries, minus audit
        shrinkage and POS exits. Uses independent Subqueries (not multiple
        Sum()s on sibling reverse relations in one annotate()) — combining
        them directly would JOIN entries × audits × exits and inflate each
        sum by the other tables' row counts. Keep in sync with
        `inventory.services.get_current_stock`, which does the same
        computation for single-instance use (e.g. right after saving a new
        entry, before the queryset would reflect it in a fresh query).
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
            - Coalesce(Subquery(exits_total, output_field=IntegerField()), 0)
        )


class Product(TimeStampedModel):
    sku = models.CharField(max_length=50, unique=True)
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
    # Running weighted-average cost, updated by InventoryEntry.unit_cost —
    # never edited directly (see inventory.services.apply_stock_entry_cost).
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    suggested_price = models.DecimalField(max_digits=10, decimal_places=2)
    min_stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["base_model"]

    def __str__(self):
        return f"{self.sku} — {self.base_model}"


class PriceTier(TimeStampedModel):
    """A quantity breakpoint below which the flat `suggested_price` applies
    (min_quantity starts at 2 — the qty=1 case is just suggested_price)."""

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
        return f"{self.product.sku} — {self.min_quantity}+: {self.unit_price}"


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
        return f"{self.date} — {self.product.sku} (+{self.quantity})"


class InventoryAudit(TimeStampedModel):
    date = models.DateField()
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="audits")
    physical_count = models.IntegerField()
    # Snapshot of what the system expected before this audit's correction,
    # and the resulting deltas — frozen at creation, never recalculated.
    theoretical_stock_snapshot = models.IntegerField()
    loss_adjustment = models.IntegerField()
    loss_value = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.date} — {self.product.sku} (ajuste {self.loss_adjustment})"
