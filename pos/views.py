from rest_framework import viewsets

from .models import Sale
from .serializers import SaleSerializer


class SaleViewSet(viewsets.ModelViewSet):
    queryset = (
        Sale.objects.select_related("customer")
        .prefetch_related("lines__product", "lines__payment_method")
        .all()
    )
    serializer_class = SaleSerializer
    filterset_fields = ["customer", "date"]
