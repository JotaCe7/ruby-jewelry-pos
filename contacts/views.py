from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser

from core.permissions import IsAdminOrReadOnly

from .models import Customer, Supplier
from .serializers import CustomerSerializer, SupplierSerializer


class SupplierViewSet(viewsets.ModelViewSet):
    # Purchasing/finance concept — a Vendedor never touches suppliers.
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [IsAdminUser]


class CustomerViewSet(viewsets.ModelViewSet):
    # A Vendedor picks a customer at checkout, so this needs to stay
    # readable for them, just not editable.
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [IsAdminOrReadOnly]
