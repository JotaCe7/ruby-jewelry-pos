from django.urls import path

from .views import SummaryView, TodayView

app_name = "dashboard"

urlpatterns = [
    path("today/", TodayView.as_view(), name="today"),
    path("summary/", SummaryView.as_view(), name="summary"),
]
