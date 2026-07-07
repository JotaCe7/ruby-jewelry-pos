from collections import defaultdict
from decimal import Decimal

from django.db.models import F, Sum
from django.db.models.functions import Coalesce

from inventory.models import InventoryAudit, Product
from pos.models import CashRegisterSession, ClosingType, InventoryExit, MovementType
from pos.services import compute_closing_totals, get_process_date


def get_today_snapshot():
    """Live, in-progress numbers for the Admin walking the floor: each
    seller's sales since they opened their register today (same math as
    an X-closing preview, just without the PIN gate — nothing is executed
    or persisted here), plus which products need restocking right now."""
    sellers = []
    for session in CashRegisterSession.objects.select_related("seller").order_by("seller__username"):
        entry = {
            "seller_id": session.seller_id,
            "username": session.seller.username,
            "is_open": session.is_open,
            "opened_at": session.opened_at,
        }
        if session.is_open:
            entry.update(compute_closing_totals(session.seller, ClosingType.X))
        sellers.append(entry)

    low_stock = (
        Product.objects.with_stock()
        .filter(is_active=True, current_stock__lte=F("min_stock"))
        .order_by("current_stock")
    )

    return {
        "process_date": get_process_date(),
        "sellers": sellers,
        "low_stock_products": [
            {
                "id": p.id,
                "sku": p.sku,
                "base_model": p.base_model,
                "current_stock": p.current_stock,
                "min_stock": p.min_stock,
            }
            for p in low_stock
        ],
    }


def get_summary(date_from, date_to):
    """One aggregation pass over every SALE/GIFT/DAMAGED exit in range,
    computing income, per-payment-method, per-seller and per-supplier
    breakdowns together — deliberately plain Python aggregation (not
    combined annotate()s) at this shop's scale, sidestepping the
    Sum-fan-out risk documented on Product.with_stock()."""
    exits = InventoryExit.objects.filter(
        sale__date__gte=date_from, sale__date__lte=date_to
    ).select_related("product__supplier", "payment_method", "sale__seller")

    total_income = Decimal("0.00")
    by_payment_method = defaultdict(lambda: Decimal("0.00"))
    by_seller = defaultdict(
        lambda: {"total_sales": Decimal("0.00"), "sale_count": 0, "gift_count": 0, "damaged_count": 0}
    )
    by_supplier = defaultdict(lambda: {"revenue": Decimal("0.00"), "cost": Decimal("0.00")})
    by_product = defaultdict(lambda: {"revenue": Decimal("0.00"), "quantity": 0})
    gift_damaged_losses = Decimal("0.00")
    sale_ids_by_seller = defaultdict(set)

    for exit_row in exits:
        seller = exit_row.sale.seller
        seller_key = seller.id if seller else None
        seller_bucket = by_seller[seller_key]
        seller_bucket["username"] = seller.username if seller else "—"

        if exit_row.movement_type == MovementType.SALE:
            total_income += exit_row.final_price
            method_name = exit_row.payment_method.name if exit_row.payment_method else "—"
            by_payment_method[method_name] += exit_row.final_price
            seller_bucket["total_sales"] += exit_row.final_price
            sale_ids_by_seller[seller_key].add(exit_row.sale_id)

            supplier = exit_row.product.supplier
            supplier_key = supplier.id if supplier else None
            supplier_bucket = by_supplier[supplier_key]
            supplier_bucket["name"] = supplier.name if supplier else "Sin proveedor"
            supplier_bucket["revenue"] += exit_row.final_price
            supplier_bucket["cost"] += exit_row.unit_cost_snapshot * exit_row.quantity

            product_bucket = by_product[exit_row.product_id]
            product_bucket["sku"] = exit_row.product.sku
            product_bucket["base_model"] = exit_row.product.base_model
            product_bucket["revenue"] += exit_row.final_price
            product_bucket["quantity"] += exit_row.quantity
        else:
            gift_damaged_losses += exit_row.unit_cost_snapshot * exit_row.quantity
            if exit_row.movement_type == MovementType.GIFT:
                seller_bucket["gift_count"] += exit_row.quantity
            else:
                seller_bucket["damaged_count"] += exit_row.quantity

    for seller_key, sale_ids in sale_ids_by_seller.items():
        by_seller[seller_key]["sale_count"] = len(sale_ids)

    audit_shrinkage = InventoryAudit.objects.filter(date__gte=date_from, date__lte=date_to).aggregate(
        total=Coalesce(Sum("loss_value"), Decimal("0.00"))
    )["total"]

    supplier_rows = []
    for key, bucket in by_supplier.items():
        profit = bucket["revenue"] - bucket["cost"]
        margin_pct = (profit / bucket["revenue"] * 100) if bucket["revenue"] else Decimal("0.00")
        supplier_rows.append(
            {
                "supplier_id": key,
                "supplier_name": bucket["name"],
                "revenue": str(bucket["revenue"]),
                "cost": str(bucket["cost"]),
                "profit": str(profit),
                "margin_pct": str(margin_pct.quantize(Decimal("0.1"))),
            }
        )
    supplier_rows.sort(key=lambda r: Decimal(r["profit"]), reverse=True)

    seller_rows = [
        {
            "seller_id": key,
            "username": bucket["username"],
            "total_sales": str(bucket["total_sales"]),
            "sale_count": bucket["sale_count"],
            "gift_count": bucket["gift_count"],
            "damaged_count": bucket["damaged_count"],
        }
        for key, bucket in by_seller.items()
    ]
    seller_rows.sort(key=lambda r: Decimal(r["total_sales"]), reverse=True)

    top_products = [
        {
            "product_id": key,
            "sku": bucket["sku"],
            "base_model": bucket["base_model"],
            "revenue": str(bucket["revenue"]),
            "quantity": bucket["quantity"],
        }
        for key, bucket in by_product.items()
    ]
    top_products.sort(key=lambda r: Decimal(r["revenue"]), reverse=True)

    active_products = Product.objects.with_stock().filter(is_active=True)
    inventory_value = sum((p.current_stock * p.unit_cost for p in active_products), Decimal("0.00"))
    low_stock_count = sum(1 for p in active_products if p.current_stock <= p.min_stock)

    return {
        "date_from": date_from,
        "date_to": date_to,
        "total_income": str(total_income),
        "total_by_payment_method": {name: str(amount) for name, amount in by_payment_method.items()},
        "by_seller": seller_rows,
        "by_supplier": supplier_rows,
        "top_products": top_products[:10],
        "total_losses": str(gift_damaged_losses + audit_shrinkage),
        "losses_breakdown": {
            "gifts_damaged": str(gift_damaged_losses),
            "audit_shrinkage": str(audit_shrinkage),
        },
        "inventory_value": str(inventory_value),
        "low_stock_count": low_stock_count,
    }
