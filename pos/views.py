from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AdminPin,
    CashRegisterSession,
    DraftSale,
    MovementType,
    RegisterClosing,
    Sale,
    SaleDocument,
)
from .serializers import (
    DraftSaleSerializer,
    RegisterClosingSerializer,
    SaleDocumentSerializer,
    SaleSerializer,
    VoidDocumentSerializer,
)
from .services import (
    RegisterError,
    create_sale_from_lines,
    execute_closing,
    force_open_register,
    get_process_date,
    open_register,
    preview_closing,
    set_process_date,
    void_document,
)

User = get_user_model()


class SaleViewSet(viewsets.ModelViewSet):
    # Any authenticated user can ring up a sale, but browsing/reprinting
    # tickets is scoped to "only my own sales" for a Vendedor — same
    # data-minimization precedent as removing Inventario access. Admin sees
    # everyone's, needed for the Ventas/anulación screen.
    queryset = (
        Sale.objects.select_related("customer", "seller")
        .prefetch_related("lines__product", "lines__payment_method", "documents")
        .all()
    )
    serializer_class = SaleSerializer
    filterset_fields = ["customer", "seller", "date"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            return queryset.filter(seller=self.request.user)
        return queryset

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except RegisterError as exc:
            raise ValidationError({"detail": str(exc)})


class DraftSaleView(APIView):
    """The current user's single in-progress ticket — persisted server-side
    so a dead phone or switching devices mid-sale doesn't lose it. Never
    touches stock; only `finalize` promotes it into a real Sale."""

    def get_object(self):
        draft, _ = DraftSale.objects.get_or_create(
            created_by=self.request.user, defaults={"date": get_process_date()}
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

        try:
            sale = create_sale_from_lines(draft.customer, request.user, lines_data)
        except RegisterError as exc:
            return Response({"detail": str(exc)}, status=400)

        draft.delete()
        return Response(SaleSerializer(sale).data, status=201)


class RegisterStatusView(APIView):
    """The caller's own register status plus the current global process
    date — polled by the frontend to decide whether to show the
    'abrir caja' gate before letting a Vendedor into the POS ticket."""

    def get(self, request):
        session = CashRegisterSession.objects.filter(seller=request.user).first()
        return Response(
            {
                "is_open": bool(session and session.is_open),
                "opened_at": session.opened_at if session else None,
                "process_date": get_process_date(),
            }
        )


class RegisterOpenView(APIView):
    def post(self, request):
        try:
            session = open_register(request.user)
        except RegisterError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"is_open": session.is_open, "opened_at": session.opened_at})


class RegisterForceOpenView(APIView):
    """Admin-only: force-opens another seller's register regardless of the
    'must equal today' rule — the first step of the retroactive-correction
    flow (attribute a forgotten sale to an already-Z'd date)."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        seller = get_object_or_404(User, pk=request.data.get("seller"))
        session = force_open_register(seller)
        return Response({"is_open": session.is_open, "opened_at": session.opened_at})


class RegisterSetProcessDateView(APIView):
    """Admin-only: sets the global process date directly."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        raw_date = request.data.get("date")
        new_date = parse_date(raw_date) if raw_date else None
        if not new_date:
            return Response({"detail": "date es requerido, formato YYYY-MM-DD."}, status=400)
        flags = set_process_date(new_date)
        return Response({"process_date": new_date, **flags})


class RegisterClosingActionView(APIView):
    """Runs an X or Z closing in either mode:
    - mode=PANTALLA: preview only, nothing persisted or changed.
    - mode=IMPRESORA: persists a RegisterClosing row and, for a Z, closes
      the session and (if nobody else is open) advances the process date.

    `seller` in the body is only for the narrow admin-on-behalf-of case
    (retroactive correction) — normally the caller closes their own
    register and `seller` is omitted."""

    def post(self, request):
        closing_type = request.data.get("closing_type")
        mode = request.data.get("mode")
        pin = request.data.get("pin", "")
        seller_id = request.data.get("seller")
        include_product_breakdown = bool(request.data.get("include_product_breakdown"))

        seller = request.user
        if seller_id and str(seller_id) != str(request.user.pk):
            if not request.user.is_staff:
                return Response(
                    {"detail": "Solo un administrador puede cerrar la caja de otro vendedor."}, status=403
                )
            seller = get_object_or_404(User, pk=seller_id)

        if mode not in ("PANTALLA", "IMPRESORA"):
            return Response({"detail": "mode debe ser PANTALLA o IMPRESORA."}, status=400)
        if closing_type not in ("X", "Z"):
            return Response({"detail": "closing_type debe ser X o Z."}, status=400)

        try:
            if mode == "PANTALLA":
                totals = preview_closing(
                    seller, closing_type, pin, include_product_breakdown=include_product_breakdown
                )
                return Response(totals)
            closing = execute_closing(
                seller,
                closing_type,
                pin,
                performed_by=request.user,
                include_product_breakdown=include_product_breakdown,
            )
        except RegisterError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(RegisterClosingSerializer(closing).data, status=201)


class RegisterPinView(APIView):
    """Admin-only: each admin manages their own PIN (the closing system
    checks every admin's PIN to find who's authorizing — see
    pos/models.py:AdminPin). GET reports whether the CALLING admin has set
    one yet; the hash itself is never returned."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        pin = AdminPin.objects.filter(admin=request.user).first()
        return Response({"has_pin": bool(pin and pin.pin_hash)})

    def post(self, request):
        pin = request.data.get("pin", "")
        if not pin or not pin.isdigit():
            return Response({"detail": "El PIN debe ser numérico."}, status=400)
        AdminPin.get_or_create_for(request.user).set_pin(pin)
        return Response({"has_pin": True})


class RegisterClosingViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only history of executed closings, for the future Admin
    reprint/history screen — Impresora-mode runs only, Pantalla previews
    are never persisted."""

    permission_classes = [IsAdminUser]
    queryset = RegisterClosing.objects.select_related("seller", "performed_by", "authorized_by").all()
    serializer_class = RegisterClosingSerializer
    filterset_fields = ["seller", "closing_type", "process_date"]


class SaleDocumentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only browsing of issued comprobantes (for reprinting a Nota de
    Venta or finding one to anular), plus the anulación action itself.
    Scoped to "only my own sales" for a Vendedor, same as SaleViewSet."""

    queryset = SaleDocument.objects.select_related("sale", "voided_by").all()
    serializer_class = SaleDocumentSerializer
    filterset_fields = ["document_type", "status", "sale"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            return queryset.filter(sale__seller=self.request.user)
        return queryset

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        document = self.get_object()
        serializer = VoidDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            document = void_document(
                document,
                reason=serializer.validated_data["reason"],
                pin=serializer.validated_data["pin"],
                performed_by=request.user,
            )
        except RegisterError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(SaleDocumentSerializer(document).data)
