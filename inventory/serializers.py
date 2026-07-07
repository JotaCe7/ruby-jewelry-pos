from decimal import Decimal

from rest_framework import serializers

from .models import InventoryAudit, InventoryEntry, PriceTier, Product
from .services import apply_stock_entry_cost, generate_sku, get_current_stock, get_unique_sku


class PriceTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceTier
        fields = ["id", "product", "min_quantity", "unit_price"]


class ProductSerializer(serializers.ModelSerializer):
    # Optional on input: create() auto-generates it from base_model/color/
    # presentation when left blank.
    sku = serializers.CharField(required=False, allow_blank=True)
    subcategory_name = serializers.CharField(source="subcategory.name", read_only=True)
    category_name = serializers.CharField(source="subcategory.category.name", read_only=True)
    color_name = serializers.CharField(source="color.name", read_only=True, default=None)
    presentation_name = serializers.CharField(source="presentation.name", read_only=True, default=None)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    current_stock = serializers.IntegerField(read_only=True)
    inventory_value = serializers.SerializerMethodField()
    needs_restock = serializers.SerializerMethodField()
    price_tiers = PriceTierSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "base_model",
            "image",
            "subcategory",
            "subcategory_name",
            "category_name",
            "color",
            "color_name",
            "presentation",
            "presentation_name",
            "supplier",
            "supplier_name",
            "unit_cost",
            "suggested_price",
            "min_stock",
            "is_active",
            "current_stock",
            "inventory_value",
            "needs_restock",
            "price_tiers",
        ]
        read_only_fields = ["unit_cost"]

    def get_inventory_value(self, obj) -> str:
        return str((Decimal(obj.current_stock) * obj.unit_cost).quantize(Decimal("0.01")))

    def get_needs_restock(self, obj) -> bool:
        return obj.current_stock <= obj.min_stock

    def validate_sku(self, value):
        if not value:
            return value
        queryset = Product.objects.filter(sku=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A product with this SKU already exists.")
        return value

    def create(self, validated_data):
        if not validated_data.get("sku"):
            base_sku = generate_sku(
                validated_data["base_model"],
                getattr(validated_data.get("color"), "name", ""),
                getattr(validated_data.get("presentation"), "name", ""),
            )
            validated_data["sku"] = get_unique_sku(base_sku)
        product = super().create(validated_data)
        # A brand-new product has no entries/audits yet; set it directly
        # instead of re-fetching through with_stock() for this response.
        product.current_stock = 0
        return product


class InventoryEntrySerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = InventoryEntry
        fields = ["id", "date", "product", "product_sku", "quantity", "unit_cost", "notes"]

    def create(self, validated_data):
        product = validated_data["product"]
        stock_before = get_current_stock(product)
        entry = super().create(validated_data)
        if entry.unit_cost is not None:
            apply_stock_entry_cost(product, stock_before, entry.quantity, entry.unit_cost)
        return entry


class InventoryAuditSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = InventoryAudit
        fields = [
            "id",
            "date",
            "product",
            "product_sku",
            "physical_count",
            "theoretical_stock_snapshot",
            "loss_adjustment",
            "loss_value",
        ]
        read_only_fields = ["theoretical_stock_snapshot", "loss_adjustment", "loss_value"]

    def create(self, validated_data):
        product = validated_data["product"]
        theoretical = get_current_stock(product)
        physical = validated_data["physical_count"]
        loss_adjustment = theoretical - physical
        validated_data["theoretical_stock_snapshot"] = theoretical
        validated_data["loss_adjustment"] = loss_adjustment
        validated_data["loss_value"] = (Decimal(loss_adjustment) * product.unit_cost).quantize(
            Decimal("0.01")
        )
        return super().create(validated_data)
