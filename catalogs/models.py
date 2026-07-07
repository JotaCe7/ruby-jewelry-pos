from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import NamedCatalogModel


class ExpenseCategory(NamedCatalogModel):
    class Meta(NamedCatalogModel.Meta):
        verbose_name = _("expense category")
        verbose_name_plural = _("expense categories")


class PaymentMethod(NamedCatalogModel):
    class Meta(NamedCatalogModel.Meta):
        verbose_name = _("payment method")
        verbose_name_plural = _("payment methods")


class ProductCategory(NamedCatalogModel):
    class Meta(NamedCatalogModel.Meta):
        verbose_name = _("product category")
        verbose_name_plural = _("product categories")


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


class ColorVariant(NamedCatalogModel):
    class Meta(NamedCatalogModel.Meta):
        verbose_name = _("color variant")
        verbose_name_plural = _("color variants")


class Presentation(NamedCatalogModel):
    class Meta(NamedCatalogModel.Meta):
        verbose_name = _("presentation")
        verbose_name_plural = _("presentations")
