from django.utils import timezone
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DraftSale, MovementType, Sale
from .serializers import DraftSaleSerializer, SaleSerializer
from .services import create_sale_from_lines


class SaleViewSet(viewsets.ModelViewSet):
    # Any authenticated user (Admin or Vendedor) can ring up a sale; not
    # scoped to "only my own sales" yet — see project memory for why.
    queryset = (
        Sale.objects.select_related("customer", "seller")
        .prefetch_related("lines__product", "lines__payment_method")
        .all()
    )
    serializer_class = SaleSerializer
    filterset_fields = ["customer", "seller", "date"]


class DraftSaleView(APIView):
    """The current user's single in-progress ticket — persisted server-side
    so a dead phone or switching devices mid-sale doesn't lose it. Never
    touches stock; only `finalize` promotes it into a real Sale."""

    def get_object(self):
        draft, _ = DraftSale.objects.get_or_create(
            created_by=self.request.user, defaults={"date": timezone.localdate()}
        )
        return draft

    def get(self, request):
        return Response(DraftSaleSerializer(self.get_object()).data)

    def patch(self, request):
        serializer = DraftSaleSerializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request):
        DraftSale.objects.filter(created_by=request.user).delete()
        return Response(status=204)


class DraftSaleFinalizeView(APIView):
    def post(self, request):
        try:
            draft = DraftSale.objects.get(created_by=request.user)
        except DraftSale.DoesNotExist:
            return Response({"detail": "No hay ningún ticket en borrador."}, status=400)

        lines = list(draft.lines.select_related("product", "payment_method"))
        if not lines:
            return Response({"detail": "El ticket no tiene productos."}, status=400)

        for line in lines:
            if line.movement_type == MovementType.SALE and not line.payment_method:
                return Response(
                    {"detail": f"Falta el método de pago para {line.product.sku}."}, status=400
                )

        lines_data = [
            {
                "product": line.product,
                "movement_type": line.movement_type,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "discount": line.discount,
                "payment_method": line.payment_method,
                "combo_key": line.combo_key or None,
                "combo_discount_total": line.combo_discount_total,
            }
            for line in lines
        ]

        sale = create_sale_from_lines(draft.date, draft.customer, request.user, lines_data)
        draft.delete()
        return Response(SaleSerializer(sale).data, status=201)
