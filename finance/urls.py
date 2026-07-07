from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ExchangeRateView, ExpenseViewSet

app_name = "finance"

router = DefaultRouter()
router.register("expenses", ExpenseViewSet, basename="expense")

urlpatterns = [
    path("exchange-rate/", ExchangeRateView.as_view(), name="exchange-rate"),
] + router.urls
