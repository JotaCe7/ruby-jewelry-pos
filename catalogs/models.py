from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from core.models import NamedCatalogModel


class ExpenseCategory(NamedCatalogModel):
    class Meta(NamedCatalogModel.Meta):
        verbose_name = _("expense category")
        verbose_name_plural = _("expense categories")


class PaymentMethod(NamedCatalogModel):
    # Drives the finance rule that a payment reference is required unless
    # the method is cash: matched by this flag rather than the editable
    # `name`, since an admin could rename "Efectivo" at any time. NOT the
    # same concept as `is_default` below: a method can require a reference
    # (is_cash=False) and still be the one preselected in POS, e.g. "Caja"
    # (a mall's shared register, which does give a voucher to reconcile).
    is_cash = models.BooleanField(default=False)
    # Preselected payment method on a new POS ticket. Exclusive: saving a
    # method with is_default=True clears it from every other one, so this
    # never has to be enforced correctly by every caller (API, admin, shell).
    is_default = models.BooleanField(default=False)

    class Meta(NamedCatalogModel.Meta):
        verbose_name = _("payment method")
        verbose_name_plural = _("payment methods")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if self.is_default:
                PaymentMethod.objects.filter(is_default=True).exclude(pk=self.pk).update(
                    is_default=False
                )


class CategoryCodeSequence(models.Model):
    """Singleton row (always pk=1) tracking the next 2-digit
    ProductCategory.code: global, unlike Subcategory/Product codes
    which are scoped to their parent. Locked via select_for_update
    before allocating, same pattern as inventory.models.BarcodeSequence
    and pos.models.DocumentSeries' sequence number."""

    next_value = models.PositiveIntegerField(default=1)

    @classmethod
    def get_or_create_singleton(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class ProductCategory(NamedCatalogModel):
    # Shown as the folder tile when the salesperson browses the POS
    # picker in hierarchical mode.
    image = models.ImageField(upload_to="product_categories/", null=True, blank=True)
    # Auto-generated (2-digit sequential, e.g. "01") and never editable
    # afterward. Distinct from `name`, which can be freely corrected or
    # renamed at any time.
    # editable=False also makes DRF's ModelSerializer expose this
    # read-only automatically.
    code = models.CharField(max_length=2, unique=True, editable=False, blank=True)

    class Meta(NamedCatalogModel.Meta):
        verbose_name = _("product category")
        verbose_name_plural = _("product categories")

    def save(self, *args, **kwargs):
        if not self.pk and not self.code:
            with transaction.atomic():
                sequence = CategoryCodeSequence.get_or_create_singleton()
                sequence = CategoryCodeSequence.objects.select_for_update().get(pk=sequence.pk)
                self.code = str(sequence.next_value).zfill(2)
                sequence.next_value += 1
                sequence.save(update_fields=["next_value"])
        super().save(*args, **kwargs)


class ProductSubcategory(NamedCatalogModel):
    # Overrides the abstract parent's globally-unique `name`: a subcategory
    # name is only unique within its parent category (e.g. "Individual" can
    # exist under both "Jewelry" and "Packaging").
    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.PROTECT,
        related_name="subcategories",
    )
    image = models.ImageField(upload_to="product_subcategories/", null=True, blank=True)
    # Auto-generated as the parent category's code + a 2-digit sequential
    # number scoped to that category (e.g. "0101", "0102" under "01").
    # Never editable afterward, same reasoning as ProductCategory.code.
    code = models.CharField(max_length=4, unique=True, editable=False, blank=True)

    class Meta(NamedCatalogModel.Meta):
        verbose_name = _("product subcategory")
        verbose_name_plural = _("product subcategories")
        constraints = [
            models.UniqueConstraint(
                fields=["name", "category"], name="unique_subcategory_per_category"
            )
        ]

    def __str__(self):
        return f"{self.category.name} / {self.name}"

    def save(self, *args, **kwargs):
        if not self.pk and not self.code:
            with transaction.atomic():
                category = ProductCategory.objects.select_for_update().get(pk=self.category_id)
                # MAX-based, not count()-based: a deleted sibling must
                # never free up its number for reuse.
                existing_suffixes = [
                    int(code[len(category.code) :])
                    for code in ProductSubcategory.objects.filter(category=category).values_list(
                        "code", flat=True
                    )
                    if code
                ]
                next_suffix = max(existing_suffixes, default=0) + 1
                self.code = category.code + str(next_suffix).zfill(2)
        super().save(*args, **kwargs)


class ColorVariant(NamedCatalogModel):
    class Meta(NamedCatalogModel.Meta):
        verbose_name = _("color variant")
        verbose_name_plural = _("color variants")


class Presentation(NamedCatalogModel):
    class Meta(NamedCatalogModel.Meta):
        verbose_name = _("presentation")
        verbose_name_plural = _("presentations")
