import uuid
from collections import defaultdict
from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from catalogs.models import PaymentMethod
from inventory.models import Product

from .models import InventoryExit, MovementType, Sale
from .services import ComboProrationService


class SaleLineInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    movement_type = serializers.ChoiceField(choices=MovementType.choices, default=MovementType.SALE)
    quantity = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    discount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, default=Decimal("0.00")
    )
    payment_method = serializers.PrimaryKeyRelatedField(
        queryset=PaymentMethod.objects.all(), required=False, allow_null=True
    )
    # combo_key is a client-chosen label (not persisted as-is) used only to
    # group these lines for proration; a real UUID is generated per group.
    combo_key = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    combo_discount_total = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )


class InventoryExitSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.base_model", read_only=True)
    payment_method_name = serializers.CharField(
        source="payment_method.name", read_only=True, default=None
    )

    class Meta:
        model = InventoryExit
        fields = [
            "id",
            "product",
            "product_sku",
            "product_name",
            "movement_type",
            "quantity",
            "unit_price_snapshot",
            "discount_applied",
            "final_price",
            "payment_method",
            "payment_method_name",
            "combo_group",
        ]


class SaleSerializer(serializers.ModelSerializer):
    lines = SaleLineInputSerializer(many=True, write_only=True)
    line_items = InventoryExitSerializer(source="lines", many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True, default=None)
    total = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = ["id", "date", "customer", "customer_name", "lines", "line_items", "total"]

    def get_total(self, obj) -> str:
        total = sum((line.final_price for line in obj.lines.all()), Decimal("0.00"))
        return str(total)

    def validate_lines(self, lines):
        if not lines:
            raise serializers.ValidationError(_("At least one line is required."))
        for line in lines:
            if line["movement_type"] == MovementType.SALE and not line.get("payment_method"):
                raise serializers.ValidationError(
                    _("payment_method is required for sale lines.")
                )
        return lines

    def create(self, validated_data):
        lines_data = validated_data.pop("lines")
        sale = Sale.objects.create(**validated_data)

        standalone_lines = []
        combo_groups = defaultdict(list)
        for line in lines_data:
            combo_key = line.get("combo_key")
            if combo_key:
                combo_groups[combo_key].append(line)
            else:
                standalone_lines.append(line)

        for line in standalone_lines:
            self._create_line(sale, line, discount=line.get("discount") or Decimal("0.00"))

        for group_lines in combo_groups.values():
            combo_group_id = uuid.uuid4()
            total_discount = group_lines[0].get("combo_discount_total") or Decimal("0.00")
            weights = [line["unit_price"] * line["quantity"] for line in group_lines]
            discounts = ComboProrationService.apply(weights, total_discount)
            for line, discount in zip(group_lines, discounts):
                self._create_line(sale, line, discount=discount, combo_group=combo_group_id)

        return sale

    def _create_line(self, sale, line, discount, combo_group=None):
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
