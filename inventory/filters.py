import django_filters

from .models import Product


class NumberInFilter(django_filters.BaseInFilter, django_filters.NumberFilter):
    """Enables ?field=1,2,3 style multi-value filtering, e.g. for the POS
    picker's "one or more categories/subcategories/suppliers" filters."""


class ProductFilter(django_filters.FilterSet):
    subcategory = NumberInFilter(field_name="subcategory")
    category = NumberInFilter(field_name="subcategory__category")
    supplier = NumberInFilter(field_name="supplier")
    # Ruta 2 (scan/type SKU): case-insensitive contains so a partial scan
    # or manual entry still narrows results, not just an exact match.
    sku = django_filters.CharFilter(field_name="sku", lookup_expr="icontains")

    class Meta:
        model = Product
        fields = ["subcategory", "category", "supplier", "is_active", "sku"]
