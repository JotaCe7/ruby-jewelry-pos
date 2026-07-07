from rest_framework import viewsets

from .models import Customer, Supplier
from .serializers import CustomerSerializer, SupplierSerializer


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
