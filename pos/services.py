import uuid
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class RegisterError(Exception):
    """Base for all register/closing business-rule violations. Views catch
    this one class and turn it into a 400 with the message as-is."""


class RegisterClosedError(RegisterError):
    pass


class RegisterAlreadyOpenError(RegisterError):
    pass


class ProcessDateBlockedError(RegisterError):
    pass


class InvalidPinError(RegisterError):
    pass


class DocumentNotVoidableError(RegisterError):
    pass


class ComboProrationService:
    """Distributes a single combo-level discount across N lines
    proportionally to each line's weight (unit_price * quantity), so a
    mix-and-match combo never applies its discount to just one item. The
    rounding remainder is assigned to the last line so the parts always
    sum exactly to total_discount.
    """

    @staticmethod
    def apply(weights: list[Decimal], total_discount: Decimal) -> list[Decimal]:
        total_weight = sum(weights)
        if not total_weight:
            return [Decimal("0.00") for _ in weights]

        discounts = []
        running_total = Decimal("0.00")
        last_index = len(weights) - 1
        for index, weight in enumerate(weights):
            if index == last_index:
                discounts.append((total_discount - running_total).quantize(Decimal("0.01")))
            else:
                share = (total_discount * weight / total_weight).quantize(Decimal("0.01"))
                discounts.append(share)
                running_total += share
        return discounts


def get_process_date():
    from .models import ProcessDate

    return ProcessDate.get_or_create_default().current_date


def ensure_register_open(seller):
    """Raises unless `seller` currently has an open register. Called at the
    top of create_sale_from_lines so a sale can never be attributed to
    someone who hasn't (or no longer has) their register open."""
    from .models import CashRegisterSession

    session = CashRegisterSession.objects.filter(seller=seller, is_open=True).first()
    if not session:
        raise RegisterClosedError(_("This seller's register isn't open. Open it before selling."))
    return session


def open_register(user):
    """Self-service open. A Seller can only open onto 'today'; if the
    global process date is behind today and nobody else has a session open
    (i.e. the gap days had no activity at all), it jumps straight to today
    instead of forcing empty closings for the skipped days."""
    from .models import CashRegisterSession, ProcessDate

    session, _created = CashRegisterSession.objects.get_or_create(seller=user)
    if session.is_open:
        raise RegisterAlreadyOpenError(_("Your register is already open."))

    process_date_obj = ProcessDate.get_or_create_default()
    today = timezone.localdate()

    if process_date_obj.current_date < today:
        if CashRegisterSession.objects.filter(is_open=True).exists():
            raise ProcessDateBlockedError(
                _("Another register is still open on the previous process date. Wait for it to close.")
            )
        process_date_obj.current_date = today
        process_date_obj.save(update_fields=["current_date"])
    elif process_date_obj.current_date > today:
        raise ProcessDateBlockedError(
            _("The process date is ahead of today. Contact the administrator.")
        )

    session.is_open = True
    session.opened_at = timezone.now()
    session.save(update_fields=["is_open", "opened_at"])
    return session


def force_open_register(seller):
    """Admin-only escape hatch: opens a specific seller's register under
    whatever the current process_date already is, skipping the 'must equal
    today' rule. Used to attribute a forgotten sale to an already-closed
    date, right before that seller (or the admin) redoes their Z."""
    from .models import CashRegisterSession

    session, _created = CashRegisterSession.objects.get_or_create(seller=seller)
    session.is_open = True
    session.opened_at = timezone.now()
    session.save(update_fields=["is_open", "opened_at"])
    return session


def set_process_date(new_date):
    """Admin-only: sets the global process date directly. Returns warning
    flags for the caller (view layer) to surface before/after confirming;
    this function itself never blocks the change."""
    from .models import ProcessDate, RegisterClosing

    today = timezone.localdate()
    process_date_obj = ProcessDate.get_or_create_default()
    process_date_obj.current_date = new_date
    process_date_obj.save(update_fields=["current_date"])

    return {
        "is_future": new_date > today,
        "has_prior_z": RegisterClosing.objects.filter(process_date=new_date, closing_type="Z").exists(),
    }


def _closing_period(seller, closing_type):
    """Start/end of the window a closing should total up: from the end of
    the seller's last relevant closing since they opened, up to now. An X
    resets against the last X-or-Z; a Z resets against the last Z only. So
    intermediate X's don't shrink what the Z reports. A Z always totals
    everything since the previous Z."""
    from .models import CashRegisterSession, ClosingType, RegisterClosing

    session = CashRegisterSession.objects.filter(seller=seller).first()
    opened_at = session.opened_at if session and session.opened_at else timezone.now()

    relevant_types = [ClosingType.Z] if closing_type == ClosingType.Z else [ClosingType.X, ClosingType.Z]
    last_closing = (
        RegisterClosing.objects.filter(seller=seller, created_at__gte=opened_at, closing_type__in=relevant_types)
        .order_by("-created_at")
        .first()
    )
    period_start = last_closing.period_end if last_closing else opened_at
    period_end = timezone.now()
    return period_start, period_end


def _document_breakdown(seller, period_start, period_end):
    """Per (document_type, series) issued in the period: first/last
    sequence number (voided documents keep their number in this range,
    since a sequence number is never skipped) and the combined amount of
    the non-voided ones only."""
    from .models import DocumentStatus, SaleDocument

    documents = SaleDocument.objects.filter(
        sale__seller=seller, created_at__gte=period_start, created_at__lt=period_end
    ).order_by("sequence_number")

    groups = {}
    for document in documents:
        key = (document.document_type, document.series)
        group = groups.get(key)
        if group is None:
            group = {
                "document_type": document.document_type,
                "document_type_display": document.get_document_type_display(),
                "series": document.series,
                "first_number": document.sequence_number,
                "last_number": document.sequence_number,
                "count": 0,
                "amount": Decimal("0.00"),
            }
            groups[key] = group
        group["first_number"] = min(group["first_number"], document.sequence_number)
        group["last_number"] = max(group["last_number"], document.sequence_number)
        group["count"] += 1
        if document.status != DocumentStatus.VOIDED:
            group["amount"] += document.total

    return [{**group, "amount": str(group["amount"])} for group in groups.values()]


def _sale_exits_in_period(seller, period_start, period_end):
    """SALE-movement lines (never GIFT/DAMAGED, never voided) in the
    period. Shared base query for category/product breakdowns."""
    from .models import InventoryExit, MovementType

    return InventoryExit.objects.filter(
        sale__seller=seller,
        sale__created_at__gte=period_start,
        sale__created_at__lt=period_end,
        sale__is_voided=False,
        movement_type=MovementType.SALE,
    )


def _category_breakdown(seller, period_start, period_end):
    exits = _sale_exits_in_period(seller, period_start, period_end).select_related(
        "product__subcategory__category"
    )

    groups = defaultdict(lambda: {"quantity": 0, "amount": Decimal("0.00")})
    for exit_row in exits:
        category = exit_row.product.subcategory.category
        bucket = groups[category.id]
        bucket["category_name"] = category.name
        bucket["quantity"] += exit_row.quantity
        bucket["amount"] += exit_row.final_price

    result = [
        {"category_id": category_id, **bucket, "amount": str(bucket["amount"])}
        for category_id, bucket in groups.items()
    ]
    result.sort(key=lambda row: Decimal(row["amount"]), reverse=True)
    return result


def _product_breakdown(seller, period_start, period_end):
    exits = _sale_exits_in_period(seller, period_start, period_end).select_related("product")

    groups = defaultdict(lambda: {"quantity": 0, "amount": Decimal("0.00")})
    for exit_row in exits:
        bucket = groups[exit_row.product_id]
        bucket["sku"] = exit_row.product.sku
        bucket["base_model"] = exit_row.product.base_model
        bucket["quantity"] += exit_row.quantity
        bucket["amount"] += exit_row.final_price

    result = [
        {"product_id": product_id, **bucket, "amount": str(bucket["amount"])}
        for product_id, bucket in groups.items()
    ]
    result.sort(key=lambda row: Decimal(row["amount"]), reverse=True)
    return result


def compute_closing_totals(seller, closing_type, include_product_breakdown=False):
    from .models import InventoryExit, MovementType

    period_start, period_end = _closing_period(seller, closing_type)
    exits = InventoryExit.objects.filter(
        sale__seller=seller,
        sale__created_at__gte=period_start,
        sale__created_at__lt=period_end,
        sale__is_voided=False,
    ).select_related("payment_method")

    total_sales = Decimal("0.00")
    by_payment_method = defaultdict(lambda: Decimal("0.00"))
    total_losses = Decimal("0.00")
    sale_ids = set()

    for exit_row in exits:
        sale_ids.add(exit_row.sale_id)
        if exit_row.movement_type == MovementType.SALE:
            total_sales += exit_row.final_price
            method_name = exit_row.payment_method.name if exit_row.payment_method else "N/A"
            by_payment_method[method_name] += exit_row.final_price
        else:
            total_losses += exit_row.unit_cost_snapshot * exit_row.quantity

    return {
        "period_start": period_start,
        "period_end": period_end,
        "total_sales": str(total_sales),
        "total_by_payment_method": {name: str(amount) for name, amount in by_payment_method.items()},
        "total_losses": str(total_losses),
        "sale_count": len(sale_ids),
        "document_breakdown": _document_breakdown(seller, period_start, period_end),
        "category_breakdown": _category_breakdown(seller, period_start, period_end),
        "product_breakdown": (
            _product_breakdown(seller, period_start, period_end) if include_product_breakdown else None
        ),
    }


def preview_closing(seller, closing_type, pin, include_product_breakdown=False):
    """Pantalla mode: validates the PIN and returns the totals without
    persisting anything or touching the register's is_open state."""
    from .models import AdminPin, ClosingType

    admin = AdminPin.find_by_pin(pin)
    if not admin:
        raise InvalidPinError(_("Incorrect PIN."))
    totals = compute_closing_totals(seller, closing_type, include_product_breakdown=include_product_breakdown)
    if closing_type == ClosingType.Z:
        totals["authorized_by_username"] = admin.username
    return totals


def execute_closing(seller, closing_type, pin, performed_by, include_product_breakdown=False):
    """Impresora mode: validates the PIN, persists a RegisterClosing row,
    and, for a Z, closes the seller's session and advances the global
    process date once no session remains open for it."""
    from .models import AdminPin, CashRegisterSession, ClosingType, ProcessDate, RegisterClosing

    admin = AdminPin.find_by_pin(pin)
    if not admin:
        raise InvalidPinError(_("Incorrect PIN."))

    totals = compute_closing_totals(seller, closing_type, include_product_breakdown=include_product_breakdown)

    with transaction.atomic():
        closing = RegisterClosing.objects.create(
            seller=seller,
            closing_type=closing_type,
            process_date=get_process_date(),
            period_start=totals["period_start"],
            period_end=totals["period_end"],
            total_sales=totals["total_sales"],
            total_by_payment_method=totals["total_by_payment_method"],
            total_losses=totals["total_losses"],
            sale_count=totals["sale_count"],
            performed_by=performed_by,
            authorized_by=admin if closing_type == ClosingType.Z else None,
            document_breakdown=totals["document_breakdown"],
            category_breakdown=totals["category_breakdown"],
            product_breakdown=totals["product_breakdown"],
        )

        if closing_type == ClosingType.Z:
            CashRegisterSession.objects.filter(seller=seller).update(is_open=False)

            if not CashRegisterSession.objects.filter(is_open=True).exists():
                process_date_obj = ProcessDate.get_or_create_default()
                process_date_obj.current_date = process_date_obj.current_date + timedelta(days=1)
                process_date_obj.save(update_fields=["current_date"])

    return closing


def issue_document(sale, document_type=None):
    """Allocates the next gapless sequence number for `document_type`
    (locking the DocumentSeries row so two concurrent sales never collide)
    and snapshots the customer's identity + IGV-inclusive totals at this
    instant. Only ever called with SALES_RECEIPT today. The other types
    become reachable through this same function once real electronic
    invoicing exists, without a schema change."""
    from .models import DocumentSeries, DocumentType, SaleDocument

    document_type = document_type or DocumentType.SALES_RECEIPT
    customer = sale.customer

    DocumentSeries.get_or_create_default(document_type)
    series_row = DocumentSeries.objects.select_for_update().get(document_type=document_type)
    sequence_number = series_row.next_sequence_number
    series_row.next_sequence_number += 1
    series_row.save(update_fields=["next_sequence_number"])

    total = sum((line.final_price for line in sale.lines.all()), Decimal("0.00"))
    subtotal = (total / Decimal("1.18")).quantize(Decimal("0.01"))
    tax_amount = total - subtotal

    return SaleDocument.objects.create(
        sale=sale,
        document_type=document_type,
        series=series_row.series,
        sequence_number=sequence_number,
        customer_name=customer.name if customer else "",
        customer_document_type=customer.document_type if customer else "",
        customer_document_number=customer.tax_id if customer else "",
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
    )


def issue_credit_note(original_document, performed_by):
    """Internal Credit Note issued the instant a Sales Receipt is voided.
    Not a real SUNAT document (a Sales Receipt isn't fiscal
    either), but it gives every void its own gapless sequence number, and
    critically it's dated *today* regardless of when the original sale
    happened. That's what makes a retroactive correction of an
    already-closed period's sale show up in *today's* Closing document
    breakdown, instead of silently rewriting a period whose totals were
    already printed and handed to someone."""
    from .models import DocumentSeries, DocumentType, SaleDocument

    DocumentSeries.get_or_create_default(DocumentType.CREDIT_NOTE)
    series_row = DocumentSeries.objects.select_for_update().get(document_type=DocumentType.CREDIT_NOTE)
    sequence_number = series_row.next_sequence_number
    series_row.next_sequence_number += 1
    series_row.save(update_fields=["next_sequence_number"])

    return SaleDocument.objects.create(
        sale=original_document.sale,
        document_type=DocumentType.CREDIT_NOTE,
        series=series_row.series,
        sequence_number=sequence_number,
        customer_name=original_document.customer_name,
        customer_document_type=original_document.customer_document_type,
        customer_document_number=original_document.customer_document_number,
        subtotal=original_document.subtotal,
        tax_amount=original_document.tax_amount,
        total=original_document.total,
        related_document=original_document,
    )


def void_document(document, reason, pin, performed_by):
    """Voiding: only a Sales Receipt can be voided today. Restores the
    stock it moved via a compensating InventoryEntry per line (no
    unit_cost, so the product's weighted-average cost is untouched, the
    same convention as any purely physical stock movement), marks both the
    document and its Sale voided (so every revenue aggregation,
    compute_closing_totals and dashboard, excludes it from then on), and
    issues an internal Credit Note referencing it (see
    issue_credit_note). Returns (voided_document, credit_note)."""
    from inventory.models import InventoryEntry

    from .models import AdminPin, DocumentStatus, DocumentType

    if document.document_type != DocumentType.SALES_RECEIPT:
        raise DocumentNotVoidableError(_("Only Sales Receipts can be voided for now."))
    if document.status == DocumentStatus.VOIDED:
        raise DocumentNotVoidableError(_("This document has already been voided."))
    if not AdminPin.find_by_pin(pin):
        raise InvalidPinError(_("Incorrect PIN."))

    with transaction.atomic():
        sale = document.sale
        for exit_row in sale.lines.select_related("product").all():
            InventoryEntry.objects.create(
                date=get_process_date(),
                product=exit_row.product,
                quantity=exit_row.quantity,
                notes=_("Return from voiding %(series)s-%(sequence_number)06d.")
                % {"series": document.series, "sequence_number": document.sequence_number},
            )

        sale.is_voided = True
        sale.save(update_fields=["is_voided"])

        document.status = DocumentStatus.VOIDED
        document.voided_at = timezone.now()
        document.voided_by = performed_by
        document.void_reason = reason
        document.save(update_fields=["status", "voided_at", "voided_by", "void_reason"])

        credit_note = issue_credit_note(document, performed_by)

    return document, credit_note


def create_sale_from_lines(customer, seller, lines_data):
    """Creates a Sale + its InventoryExit lines from plain line dicts,
    running combo proration exactly once. Shared by the direct
    POST /api/pos/sales/ endpoint and DraftSale.finalize, so a draft
    promoted to a real sale goes through identical logic to one created
    in a single request.

    The sale is always dated to the current global process date, never a
    client-supplied one, and requires `seller` to have an open register.
    Issuing its Sales Receipt happens in the same transaction, so a sale
    is never left without its printable document.

    Each line dict has: product, movement_type, quantity, unit_price,
    discount, payment_method, combo_key, combo_discount_total.
    """
    from .models import InventoryExit, MovementType, Sale

    ensure_register_open(seller)

    with transaction.atomic():
        sale = Sale.objects.create(date=get_process_date(), customer=customer, seller=seller)

        standalone_lines = []
        combo_groups = defaultdict(list)
        for line in lines_data:
            combo_key = line.get("combo_key")
            if combo_key:
                combo_groups[combo_key].append(line)
            else:
                standalone_lines.append(line)

        def create_exit(line, discount, combo_group=None):
            movement_type = line["movement_type"]
            is_sale = movement_type == MovementType.SALE
            quantity = line["quantity"]
            unit_price = line["unit_price"]

            final_price = Decimal("0.00")
            if is_sale:
                final_price = max(unit_price * quantity - discount, Decimal("0.00"))

            InventoryExit.objects.create(
                sale=sale,
                product=line["product"],
                movement_type=movement_type,
                quantity=quantity,
                unit_price_snapshot=unit_price,
                unit_cost_snapshot=line["product"].unit_cost,
                discount_applied=discount if is_sale else Decimal("0.00"),
                final_price=final_price,
                payment_method=line.get("payment_method") if is_sale else None,
                combo_group=combo_group,
            )

        for line in standalone_lines:
            create_exit(line, discount=line.get("discount") or Decimal("0.00"))

        for group_lines in combo_groups.values():
            combo_group_id = uuid.uuid4()
            total_discount = group_lines[0].get("combo_discount_total") or Decimal("0.00")
            weights = [line["unit_price"] * line["quantity"] for line in group_lines]
            discounts = ComboProrationService.apply(weights, total_discount)
            for line, discount in zip(group_lines, discounts):
                create_exit(line, discount=discount, combo_group=combo_group_id)

        issue_document(sale)

    return sale
