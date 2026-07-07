import datetime

from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from integrations.services import ExchangeRateService, ExchangeRateUnavailable

from .models import Expense
from .serializers import ExpenseSerializer


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.select_related("category", "supplier", "payment_method").all()
    serializer_class = ExpenseSerializer
    filterset_fields = ["category", "supplier", "currency", "payment_method"]


class ExchangeRateView(APIView):
    """Live preview used by the Expense form while the user is filling it
    in; the authoritative value is (re)computed server-side on save."""

    def get(self, request):
        date_param = request.query_params.get("date")
        currency = request.query_params.get("currency", "PEN")

        try:
            date = datetime.date.fromisoformat(date_param) if date_param else datetime.date.today()
        except ValueError:
            return Response({"detail": "Invalid date."}, status=400)

        try:
            value = ExchangeRateService.get_for(date, currency)
        except ExchangeRateUnavailable as exc:
            return Response({"detail": str(exc)}, status=502)

        return Response({"value": value, "date": date, "currency": currency})
