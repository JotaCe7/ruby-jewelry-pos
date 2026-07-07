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
