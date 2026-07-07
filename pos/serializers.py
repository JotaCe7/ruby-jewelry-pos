from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from catalogs.models import PaymentMethod
from inventory.models import Product
from inventory.serializers import ProductSerializer

from .models import DraftSale, DraftSaleLine, InventoryExit, MovementType, Sale
from .services import create_sale_from_lines


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
    seller_name = serializers.CharField(source="seller.username", read_only=True, default=None)
    total = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = [
            "id",
            "date",
            "customer",
            "customer_name",
            "seller_name",
            "lines",
            "line_items",
            "total",
        ]

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
        seller = self.context["request"].user
        return create_sale_from_lines(
            validated_data["date"], validated_data.get("customer"), seller, lines_data
        )


class DraftSaleLineSerializer(serializers.ModelSerializer):
    product_detail = ProductSerializer(source="product", read_only=True)

    class Meta:
        model = DraftSaleLine
        fields = [
            "id",
            "product",
            "product_detail",
            "movement_type",
            "quantity",
            "unit_price",
            "discount",
            "payment_method",
            "combo_key",
            "combo_discount_total",
        ]


class DraftSaleSerializer(serializers.ModelSerializer):
    # Deliberately lenient (no cross-field validation like the required
    # payment_method-for-SALE rule) — a draft is a work in progress by
    # definition; that rule is enforced only at finalize time.
    lines = DraftSaleLineSerializer(many=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True, default=None)

    class Meta:
        model = DraftSale
        fields = ["id", "date", "customer", "customer_name", "lines"]

    def update(self, instance, validated_data):
        lines_data = validated_data.pop("lines", None)
        instance.date = validated_data.get("date", instance.date)
        instance.customer = validated_data.get("customer", instance.customer)
        instance.save()
        if lines_data is not None:
            instance.lines.all().delete()
            DraftSaleLine.objects.bulk_create(
                DraftSaleLine(draft_sale=instance, **line) for line in lines_data
            )
        return instance
