from rest_framework import serializers

from .models import Customer, Supplier


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "tax_id", "phone", "email", "is_active"]


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "name", "tax_id", "phone", "email", "is_active"]
