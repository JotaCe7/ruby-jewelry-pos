from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import InventoryAudit, InventoryDamage, InventoryEntry, PackPrice, PriceTier, Product
from .services import apply_stock_entry_cost, generate_barcode, get_current_stock


class PriceTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceTier
        fields = ["id", "product", "min_quantity", "unit_price"]


class PriceTierCopySerializer(serializers.Serializer):
    source_product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    target_products = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), many=True)


class PackPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PackPrice
        fields = ["id", "product", "pack_quantity", "pack_price"]


class ProductSerializer(serializers.ModelSerializer):
    # sku is read-only (Product.editable=False). Product.save() assigns
    # it as the parent subcategory's hierarchical code + a sequential
    # suffix, never user input, per DRF auto-detecting editable=False.
    # Optional on input: create() auto-generates a sequential EAN-13 when
    # left blank, though it remains editable, e.g. to use a supplier's own barcode.
    barcode = serializers.CharField(required=False, allow_blank=True)
    subcategory_name = serializers.CharField(source="subcategory.name", read_only=True)
    category_name = serializers.CharField(source="subcategory.category.name", read_only=True)
    color_name = serializers.CharField(source="color.name", read_only=True, default=None)
    presentation_name = serializers.CharField(source="presentation.name", read_only=True, default=None)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    current_stock = serializers.SerializerMethodField()
    inventory_value = serializers.SerializerMethodField()
    needs_restock = serializers.SerializerMethodField()
    price_tiers = PriceTierSerializer(many=True, read_only=True)
    pack_price = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "barcode",
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
            "pack_price",
        ]
        read_only_fields = ["unit_cost"]

    def get_pack_price(self, obj) -> dict | None:
        if not hasattr(obj, "pack_price"):
            return None
        return PackPriceSerializer(obj.pack_price).data

    def get_current_stock(self, obj) -> int:
        # `with_stock()` annotates this on list/retrieve queries; instances
        # reached some other way (e.g. nested inside another serializer)
        # fall back to the single-instance equivalent computation.
        if hasattr(obj, "current_stock"):
            return obj.current_stock
        return get_current_stock(obj)

    def get_inventory_value(self, obj) -> str:
        return str((Decimal(self.get_current_stock(obj)) * obj.unit_cost).quantize(Decimal("0.01")))

    def get_needs_restock(self, obj) -> bool:
        return self.get_current_stock(obj) <= obj.min_stock

    def validate_barcode(self, value):
        if not value:
            return value
        queryset = Product.objects.filter(barcode=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(_("A product with this barcode already exists."))
        return value

    def create(self, validated_data):
        if not validated_data.get("barcode"):
            validated_data["barcode"] = generate_barcode()
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


class InventoryDamageSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    responsible_username = serializers.CharField(source="responsible.username", read_only=True, default=None)
    reported_by_username = serializers.CharField(source="reported_by.username", read_only=True)

    class Meta:
        model = InventoryDamage
        fields = [
            "id",
            "date",
            "product",
            "product_sku",
            "quantity",
            "unit_cost_snapshot",
            "reason",
            "responsible",
            "responsible_username",
            "responsible_other",
            "reported_by",
            "reported_by_username",
        ]
        read_only_fields = ["unit_cost_snapshot", "reported_by"]

    def create(self, validated_data):
        validated_data["unit_cost_snapshot"] = validated_data["product"].unit_cost
        validated_data["reported_by"] = self.context["request"].user
        return super().create(validated_data)
