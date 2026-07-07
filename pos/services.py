import uuid
from collections import defaultdict
from decimal import Decimal


class ComboProrationService:
    """Distributes a single combo-level discount across N lines
    proportionally to each line's weight (unit_price * quantity), so a
    mix-and-match combo never applies its discount to just one item. The
    rounding remainder is assigned to the last line so the parts always
    sum exactly to total_discount.
    """

    @staticmethod
    def apply(weights: list[Decimal], total_discount: Decimal) -> list[Decimal]:
        total_weight = sum(weights)
        if not total_weight:
            return [Decimal("0.00") for _ in weights]

        discounts = []
        running_total = Decimal("0.00")
        last_index = len(weights) - 1
        for index, weight in enumerate(weights):
            if index == last_index:
                discounts.append((total_discount - running_total).quantize(Decimal("0.01")))
            else:
                share = (total_discount * weight / total_weight).quantize(Decimal("0.01"))
                discounts.append(share)
                running_total += share
        return discounts


def create_sale_from_lines(date, customer, seller, lines_data):
    """Creates a Sale + its InventoryExit lines from plain line dicts,
    running combo proration exactly once. Shared by the direct
    POST /api/pos/sales/ endpoint and DraftSale.finalize, so a draft
    promoted to a real sale goes through identical logic to one created
    in a single request.

    Each line dict has: product, movement_type, quantity, unit_price,
    discount, payment_method, combo_key, combo_discount_total.
    """
    from .models import InventoryExit, MovementType, Sale

    sale = Sale.objects.create(date=date, customer=customer, seller=seller)

    standalone_lines = []
    combo_groups = defaultdict(list)
    for line in lines_data:
        combo_key = line.get("combo_key")
        if combo_key:
            combo_groups[combo_key].append(line)
        else:
            standalone_lines.append(line)

    def create_exit(line, discount, combo_group=None):
        movement_type = line["movement_type"]
        is_sale = movement_type == MovementType.SALE
        quantity = line["quantity"]
        unit_price = line["unit_price"]

        final_price = Decimal("0.00")
        if is_sale:
            final_price = max(unit_price * quantity - discount, Decimal("0.00"))

        InventoryExit.objects.create(
            sale=sale,
            product=line["product"],
            movement_type=movement_type,
            quantity=quantity,
            unit_price_snapshot=unit_price,
            discount_applied=discount if is_sale else Decimal("0.00"),
            final_price=final_price,
            payment_method=line.get("payment_method") if is_sale else None,
            combo_group=combo_group,
        )

    for line in standalone_lines:
        create_exit(line, discount=line.get("discount") or Decimal("0.00"))

    for group_lines in combo_groups.values():
        combo_group_id = uuid.uuid4()
        total_discount = group_lines[0].get("combo_discount_total") or Decimal("0.00")
        weights = [line["unit_price"] * line["quantity"] for line in group_lines]
        discounts = ComboProrationService.apply(weights, total_discount)
        for line, discount in zip(group_lines, discounts):
            create_exit(line, discount=discount, combo_group=combo_group_id)

    return sale
