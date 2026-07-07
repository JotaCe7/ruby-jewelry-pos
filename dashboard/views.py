from datetime import date

from django.utils.dateparse import parse_date
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import get_summary, get_today_snapshot


class TodayView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response(get_today_snapshot())


class SummaryView(APIView):
    """Defaults to month-to-date when no range is given — the common case
    for "how am I doing this month" — but accepts explicit date_from/
    date_to (YYYY-MM-DD) to look at any other period."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        today = date.today()
        date_from = parse_date(request.query_params.get("date_from", "")) or today.replace(day=1)
        date_to = parse_date(request.query_params.get("date_to", "")) or today
        return Response(get_summary(date_from, date_to))
