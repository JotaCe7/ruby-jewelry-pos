from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    DraftSaleFinalizeView,
    DraftSaleView,
    RegisterClosingActionView,
    RegisterClosingViewSet,
    RegisterForceOpenView,
    RegisterOpenView,
    RegisterPinView,
    RegisterSetProcessDateView,
    RegisterStatusView,
    SaleDocumentViewSet,
    SaleViewSet,
)

app_name = "pos"

router = DefaultRouter()
router.register("sales", SaleViewSet, basename="sale")
router.register("register/closings", RegisterClosingViewSet, basename="register-closing")
router.register("documents", SaleDocumentViewSet, basename="sale-document")

urlpatterns = [
    path("draft/", DraftSaleView.as_view(), name="draft"),
    path("draft/finalize/", DraftSaleFinalizeView.as_view(), name="draft-finalize"),
    path("register/status/", RegisterStatusView.as_view(), name="register-status"),
    path("register/open/", RegisterOpenView.as_view(), name="register-open"),
    path("register/force-open/", RegisterForceOpenView.as_view(), name="register-force-open"),
    path("register/set-process-date/", RegisterSetProcessDateView.as_view(), name="register-set-process-date"),
    path("register/close/", RegisterClosingActionView.as_view(), name="register-close"),
    path("register/pin/", RegisterPinView.as_view(), name="register-pin"),
] + router.urls
