from decimal import Decimal

from django.db import transaction
from django.db.models import Sum


def _ean13_check_digit(digits12: str) -> str:
    """Standard GS1 checksum: odd positions (1-indexed from the left)
    weighted ×1, even positions ×3; check digit brings the total to the
    next multiple of 10. Verified against the well-known real-world
    barcode 4006381333931 (sum=89 -> check digit 1)."""
    total = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(digits12))
    return str((10 - total % 10) % 10)


def generate_barcode() -> str:
    """Allocates the next sequential EAN-13 barcode for a Product label —
    "20" + a 10-digit sequential number + a checksum digit. "20" is
    GS1's reserved prefix range for internal/restricted-circulation use,
    so this is honest about not being a real registered retail barcode
    without needing to pay for one. Locks BarcodeSequence's single row
    (select_for_update) before allocating, mirroring
    pos.services.issue_document's correlativo locking — same
    correctness need: two concurrent product creations must never
    receive the same number."""
    from .models import BarcodeSequence

    BarcodeSequence.get_or_create_singleton()
    # select_for_update requires an open transaction — unlike
    # ProductCategory/ProductSubcategory/Product's own save() overrides,
    # which wrap their locking in transaction.atomic() themselves, this
    # is a plain function that can be called from anywhere (e.g.
    # ProductSerializer.create(), which DRF does not wrap in a
    # transaction by default), so it has to open its own.
    with transaction.atomic():
        sequence_row = BarcodeSequence.objects.select_for_update().get(pk=1)
        number = sequence_row.next_value
        sequence_row.next_value += 1
        sequence_row.save(update_fields=["next_value"])

    body = f"20{number:010d}"
    return body + _ean13_check_digit(body)


def preview_next_product_code(subcategory) -> str:
    """Best-effort preview of what Product.save() would assign to `sku`
    next — mirrors that MAX-based logic exactly (must stay in sync with
    it if it ever changes), without locking anything, since nothing is
    actually being created yet."""
    from .models import Product

    existing_suffixes = [
        int(code[len(subcategory.code) :])
        for code in Product.objects.filter(subcategory=subcategory).values_list("sku", flat=True)
        if code
    ]
    next_suffix = max(existing_suffixes, default=0) + 1
    return subcategory.code + str(next_suffix).zfill(3)


def get_current_stock(product) -> int:
    """Single-instance equivalent of ProductQuerySet.with_stock(), for use
    right after saving a row that a fresh query wouldn't reflect yet."""
    entries_total = product.entries.aggregate(total=Sum("quantity"))["total"] or 0
    audit_loss_total = product.audits.aggregate(total=Sum("loss_adjustment"))["total"] or 0
    exits_total = product.exits.aggregate(total=Sum("quantity"))["total"] or 0
    return entries_total - audit_loss_total - exits_total


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
