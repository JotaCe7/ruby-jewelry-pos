from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from integrations.services import ExchangeRateService, ExchangeRateUnavailable

from .models import Expense


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    payment_method_name = serializers.CharField(source="payment_method.name", read_only=True)
    # Only used when the live rate lookup fails for the given date; ignored
    # for PEN expenses and for USD expenses where the rate is cached/fetched.
    manual_exchange_rate = serializers.DecimalField(
        max_digits=10, decimal_places=4, required=False, allow_null=True, write_only=True
    )

    class Meta:
        model = Expense
        fields = [
            "id",
            "date",
            "category",
            "category_name",
            "description",
            "supplier",
            "supplier_name",
            "receipt_type",
            "payment_status",
            "payment_method",
            "payment_method_name",
            "payment_reference",
            "original_amount",
            "currency",
            "exchange_rate",
            "pen_equivalent_amount",
            "manual_exchange_rate",
        ]
        read_only_fields = ["exchange_rate", "pen_equivalent_amount"]

    def validate(self, attrs):
        payment_method = attrs.get("payment_method", getattr(self.instance, "payment_method", None))
        payment_reference = attrs.get(
            "payment_reference", getattr(self.instance, "payment_reference", "")
        )
        if payment_method and not payment_method.is_cash and not payment_reference:
            raise serializers.ValidationError(
                {
                    "payment_reference": _(
                        "Payment reference is required for non-cash payment methods."
                    )
                }
            )
        return attrs

    def _resolve_exchange_rate(self, date, currency, manual_exchange_rate):
        if currency == "PEN":
            return Decimal("1.0000")
        if manual_exchange_rate:
            return manual_exchange_rate
        try:
            return ExchangeRateService.get_for(date, currency)
        except ExchangeRateUnavailable as exc:
            raise serializers.ValidationError(
                {"manual_exchange_rate": [str(exc) + " " + str(_("Enter a rate manually."))]}
            ) from exc

    def create(self, validated_data):
        manual_exchange_rate = validated_data.pop("manual_exchange_rate", None)
        exchange_rate = self._resolve_exchange_rate(
            validated_data["date"], validated_data["currency"], manual_exchange_rate
        )
        validated_data["exchange_rate"] = exchange_rate
        validated_data["pen_equivalent_amount"] = (
            validated_data["original_amount"] * exchange_rate
        ).quantize(Decimal("0.01"))
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("manual_exchange_rate", None)
        date = validated_data.get("date", instance.date)
        currency = validated_data.get("currency", instance.currency)
        original_amount = validated_data.get("original_amount", instance.original_amount)
        # The exchange rate is only re-resolved if the fields it depends on
        # change — otherwise the original frozen snapshot is preserved.
        if date != instance.date or currency != instance.currency:
            validated_data["exchange_rate"] = self._resolve_exchange_rate(
                date, currency, None
            )
        exchange_rate = validated_data.get("exchange_rate", instance.exchange_rate)
        if "original_amount" in validated_data or "exchange_rate" in validated_data:
            validated_data["pen_equivalent_amount"] = (
                original_amount * exchange_rate
            ).quantize(Decimal("0.01"))
        return super().update(instance, validated_data)
