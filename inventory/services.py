import re
import unicodedata
from decimal import Decimal

from django.db.models import Sum


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _abbreviate(text: str, single_word_length: int = 3) -> str:
    """Multi-word text ('Arete Gota') becomes initials ('AG'); a single
    word ('Rojo') is truncated ('ROJ')."""
    words = re.findall(r"[A-Za-z0-9]+", _strip_accents(text).upper())
    if not words:
        return "X"
    if len(words) > 1:
        return "".join(word[0] for word in words)[:4]
    return words[0][:single_word_length]


def generate_sku(base_model: str, color_name: str = "", presentation_name: str = "") -> str:
    parts = [_abbreviate(base_model)]
    if color_name:
        parts.append(_abbreviate(color_name))
    if presentation_name:
        parts.append(_abbreviate(presentation_name))
    return "-".join(parts)


def get_unique_sku(base_sku: str, exclude_pk=None) -> str:
    from .models import Product

    candidate = base_sku
    suffix = 2
    queryset = Product.objects.all()
    if exclude_pk:
        queryset = queryset.exclude(pk=exclude_pk)
    while queryset.filter(sku=candidate).exists():
        candidate = f"{base_sku}-{suffix}"
        suffix += 1
    return candidate


def get_current_stock(product) -> int:
    """Single-instance equivalent of ProductQuerySet.with_stock(), for use
    right after saving a row that a fresh query wouldn't reflect yet."""
    entries_total = product.entries.aggregate(total=Sum("quantity"))["total"] or 0
    audit_loss_total = product.audits.aggregate(total=Sum("loss_adjustment"))["total"] or 0
    return entries_total - audit_loss_total


def apply_stock_entry_cost(product, stock_before: int, entry_quantity: int, entry_unit_cost: Decimal):
    """Recomputes the product's running weighted-average unit cost after a
    new entry, and persists it. No-op callers should skip calling this
    entirely when the entry has no unit_cost (a purely physical movement)."""
    total_before = stock_before * product.unit_cost
    total_entry = entry_quantity * entry_unit_cost
    new_stock = stock_before + entry_quantity
    product.unit_cost = (
        (total_before + total_entry) / new_stock if new_stock else Decimal("0.00")
    ).quantize(Decimal("0.01"))
    product.save(update_fields=["unit_cost"])
