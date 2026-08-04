from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from catalogs.models import PaymentMethod, ProductCategory, ProductSubcategory
from inventory.models import Product
from inventory.services import get_current_stock

from .models import (
    AdminPin,
    CashRegisterSession,
    ClosingType,
    DocumentStatus,
    DocumentType,
    ProcessDate,
)
from .services import (
    ComboProrationService,
    DocumentNotVoidableError,
    InvalidPinError,
    ProcessDateBlockedError,
    RegisterAlreadyOpenError,
    RegisterClosedError,
    compute_closing_totals,
    create_sale_from_lines,
    execute_closing,
    force_open_register,
    get_process_date,
    open_register,
    void_document,
)

User = get_user_model()


def make_product(sku="SKU-1", price="10.00", cost="4.00", category_name="Aretes"):
    category, _ = ProductCategory.objects.get_or_create(name=category_name)
    subcategory, _ = ProductSubcategory.objects.get_or_create(
        name=f"{category_name} Tier", category=category
    )
    return Product.objects.create(
        sku=sku,
        # Not exercising the real EAN-13 generator here — just needs to be
        # unique per sku so multiple make_product() calls in one test
        # don't collide on Product.barcode's unique constraint.
        barcode=sku.zfill(13)[:13],
        base_model=f"Producto {sku}",
        subcategory=subcategory,
        suggested_price=Decimal(price),
        unit_cost=Decimal(cost),
        min_stock=0,
    )


def make_payment_method(name="Efectivo", is_cash=True):
    return PaymentMethod.objects.create(name=name, is_cash=is_cash)


class ComboProrationServiceTests(TestCase):
    def test_splits_proportionally_to_weight(self):
        discounts = ComboProrationService.apply([Decimal("10.00"), Decimal("30.00")], Decimal("8.00"))
        self.assertEqual(discounts, [Decimal("2.00"), Decimal("6.00")])

    def test_remainder_goes_to_last_line(self):
        weights = [Decimal("10.00"), Decimal("10.00"), Decimal("10.00")]
        discounts = ComboProrationService.apply(weights, Decimal("10.00"))
        self.assertEqual(discounts, [Decimal("3.33"), Decimal("3.33"), Decimal("3.34")])
        self.assertEqual(sum(discounts), Decimal("10.00"))

    def test_zero_total_weight_returns_zero_discounts(self):
        discounts = ComboProrationService.apply([Decimal("0"), Decimal("0")], Decimal("5.00"))
        self.assertEqual(discounts, [Decimal("0.00"), Decimal("0.00")])


class RegisterLifecycleTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(username="seller1", password="x")

    def test_open_register_sets_open_and_opened_at(self):
        session = open_register(self.seller)
        self.assertTrue(session.is_open)
        self.assertIsNotNone(session.opened_at)

    def test_open_register_twice_raises(self):
        open_register(self.seller)
        with self.assertRaises(RegisterAlreadyOpenError):
            open_register(self.seller)

    def test_open_register_jumps_process_date_forward_when_no_one_else_open(self):
        process_date = ProcessDate.get_or_create_default()
        process_date.current_date = timezone.localdate() - timedelta(days=3)
        process_date.save()

        open_register(self.seller)

        process_date.refresh_from_db()
        self.assertEqual(process_date.current_date, timezone.localdate())

    def test_open_register_blocked_when_process_date_ahead_of_today(self):
        process_date = ProcessDate.get_or_create_default()
        process_date.current_date = timezone.localdate() + timedelta(days=1)
        process_date.save()

        with self.assertRaises(ProcessDateBlockedError):
            open_register(self.seller)

    def test_open_register_blocked_when_another_session_still_open_on_older_date(self):
        other_seller = User.objects.create_user(username="seller2", password="x")
        process_date = ProcessDate.get_or_create_default()
        process_date.current_date = timezone.localdate() - timedelta(days=1)
        process_date.save()
        CashRegisterSession.objects.create(seller=other_seller, is_open=True, opened_at=timezone.now())

        with self.assertRaises(ProcessDateBlockedError):
            open_register(self.seller)

    def test_force_open_register_ignores_today_check(self):
        process_date = ProcessDate.get_or_create_default()
        process_date.current_date = timezone.localdate() - timedelta(days=5)
        process_date.save()

        session = force_open_register(self.seller)
        self.assertTrue(session.is_open)


class CreateSaleFromLinesTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(username="seller1", password="x")
        self.payment_method = make_payment_method()
        ProcessDate.get_or_create_default()

    def _line(self, product, **overrides):
        line = {
            "product": product,
            "movement_type": "SALE",
            "quantity": 1,
            "unit_price": Decimal("10.00"),
            "discount": Decimal("0.00"),
            "payment_method": self.payment_method,
            "combo_key": None,
            "combo_discount_total": None,
        }
        line.update(overrides)
        return line

    def test_raises_when_register_closed(self):
        product = make_product()
        with self.assertRaises(RegisterClosedError):
            create_sale_from_lines(None, self.seller, [self._line(product)])

    def test_creates_sale_dated_to_process_date_and_issues_nota_de_venta(self):
        open_register(self.seller)
        product = make_product()

        sale = create_sale_from_lines(
            None, self.seller, [self._line(product, quantity=2, unit_price=Decimal("11.80"))]
        )

        self.assertEqual(sale.date, get_process_date())
        self.assertEqual(sale.documents.count(), 1)
        document = sale.documents.first()
        self.assertEqual(document.document_type, DocumentType.NOTA_VENTA)
        # Prices are IGV-inclusive: base = total / 1.18.
        self.assertEqual(document.total, Decimal("23.60"))
        self.assertEqual(document.subtotal, Decimal("20.00"))
        self.assertEqual(document.tax_amount, Decimal("3.60"))

    def test_combo_proration_applied_across_lines(self):
        open_register(self.seller)
        product1 = make_product(sku="A")
        product2 = make_product(sku="B", price="30.00")

        sale = create_sale_from_lines(
            None,
            self.seller,
            [
                self._line(
                    product1,
                    unit_price=Decimal("10.00"),
                    combo_key="combo-1",
                    combo_discount_total=Decimal("8.00"),
                ),
                self._line(
                    product2,
                    unit_price=Decimal("30.00"),
                    combo_key="combo-1",
                    combo_discount_total=Decimal("8.00"),
                ),
            ],
        )

        exits = list(sale.lines.order_by("id"))
        self.assertEqual(exits[0].discount_applied, Decimal("2.00"))
        self.assertEqual(exits[1].discount_applied, Decimal("6.00"))
        self.assertIsNotNone(exits[0].combo_group)
        self.assertEqual(exits[0].combo_group, exits[1].combo_group)

    def test_gift_line_has_zero_final_price_but_keeps_cost_snapshot(self):
        open_register(self.seller)
        product = make_product(cost="4.00")

        sale = create_sale_from_lines(
            None,
            self.seller,
            [self._line(product, movement_type="GIFT", unit_price=Decimal("10.00"), payment_method=None)],
        )

        exit_row = sale.lines.get()
        self.assertEqual(exit_row.final_price, Decimal("0.00"))
        self.assertEqual(exit_row.unit_cost_snapshot, Decimal("4.00"))


class ClosingTotalsReconciliationTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(username="seller1", password="x")
        self.admin = User.objects.create_user(username="admin1", password="x", is_staff=True)
        AdminPin.get_or_create_for(self.admin).set_pin("1234")
        ProcessDate.get_or_create_default()
        self.cash = make_payment_method("Efectivo", is_cash=True)
        open_register(self.seller)

    def _sell(self, product, qty, price, movement_type="SALE"):
        return create_sale_from_lines(
            None,
            self.seller,
            [
                {
                    "product": product,
                    "movement_type": movement_type,
                    "quantity": qty,
                    "unit_price": Decimal(price),
                    "discount": Decimal("0.00"),
                    "payment_method": self.cash if movement_type == "SALE" else None,
                    "combo_key": None,
                    "combo_discount_total": None,
                }
            ],
        )

    def test_breakdowns_reconcile_with_total_sales(self):
        product1 = make_product(sku="A", price="11.80", category_name="Aretes")
        product2 = make_product(sku="B", price="23.60", category_name="Collares")
        self._sell(product1, 2, "11.80")
        self._sell(product2, 1, "23.60")

        totals = compute_closing_totals(self.seller, ClosingType.X, include_product_breakdown=True)
        total_sales = Decimal(totals["total_sales"])

        category_sum = sum(Decimal(row["amount"]) for row in totals["category_breakdown"])
        product_sum = sum(Decimal(row["amount"]) for row in totals["product_breakdown"])
        document_sum = sum(Decimal(row["amount"]) for row in totals["document_breakdown"])

        self.assertEqual(total_sales, Decimal("47.20"))
        self.assertEqual(category_sum, total_sales)
        self.assertEqual(product_sum, total_sales)
        self.assertEqual(document_sum, total_sales)

    def test_voided_sale_excluded_from_amount_but_counted_in_document_range(self):
        product = make_product(sku="A", price="11.80")
        sale = self._sell(product, 1, "11.80")
        document = sale.documents.first()
        void_document(document, reason="test", pin="1234", performed_by=self.seller)

        totals = compute_closing_totals(self.seller, ClosingType.X)

        self.assertEqual(Decimal(totals["total_sales"]), Decimal("0.00"))
        self.assertEqual(totals["sale_count"], 0)
        doc_row = totals["document_breakdown"][0]
        self.assertEqual(doc_row["count"], 1)
        self.assertEqual(Decimal(doc_row["amount"]), Decimal("0.00"))

    def test_losses_only_count_gift_and_damaged_at_cost(self):
        product = make_product(sku="A", price="11.80", cost="4.00")
        self._sell(product, 1, "11.80")
        self._sell(product, 2, "11.80", movement_type="GIFT")

        totals = compute_closing_totals(self.seller, ClosingType.X)

        self.assertEqual(Decimal(totals["total_sales"]), Decimal("11.80"))
        self.assertEqual(Decimal(totals["total_losses"]), Decimal("8.00"))  # 2 * cost(4.00)

    def test_execute_closing_sets_authorized_by_only_for_z(self):
        product = make_product(sku="A", price="11.80")
        self._sell(product, 1, "11.80")

        x_closing = execute_closing(self.seller, ClosingType.X, "1234", performed_by=self.seller)
        self.assertIsNone(x_closing.authorized_by)

        self._sell(make_product(sku="B", price="5.00"), 1, "5.00")
        z_closing = execute_closing(self.seller, ClosingType.Z, "1234", performed_by=self.seller)
        self.assertEqual(z_closing.authorized_by, self.admin)

    def test_z_closes_session_and_advances_process_date_when_no_others_open(self):
        product = make_product(sku="A", price="11.80")
        self._sell(product, 1, "11.80")
        before = get_process_date()

        execute_closing(self.seller, ClosingType.Z, "1234", performed_by=self.seller)

        session = CashRegisterSession.objects.get(seller=self.seller)
        self.assertFalse(session.is_open)
        self.assertEqual(get_process_date(), before + timedelta(days=1))

    def test_z_does_not_advance_process_date_while_another_seller_still_open(self):
        other_seller = User.objects.create_user(username="seller2", password="x")
        open_register(other_seller)
        before = get_process_date()

        execute_closing(self.seller, ClosingType.Z, "1234", performed_by=self.seller)

        self.assertEqual(get_process_date(), before)


class VoidDocumentTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(username="seller1", password="x")
        self.admin = User.objects.create_user(username="admin1", password="x", is_staff=True)
        AdminPin.get_or_create_for(self.admin).set_pin("1234")
        ProcessDate.get_or_create_default()
        self.cash = make_payment_method()
        open_register(self.seller)
        self.product = make_product(price="11.80", cost="4.00")

    def _sell(self):
        return create_sale_from_lines(
            None,
            self.seller,
            [
                {
                    "product": self.product,
                    "movement_type": "SALE",
                    "quantity": 1,
                    "unit_price": Decimal("11.80"),
                    "discount": Decimal("0.00"),
                    "payment_method": self.cash,
                    "combo_key": None,
                    "combo_discount_total": None,
                }
            ],
        )

    def test_wrong_pin_raises(self):
        sale = self._sell()
        document = sale.documents.first()
        with self.assertRaises(InvalidPinError):
            void_document(document, reason="x", pin="9999", performed_by=self.seller)

    def test_voiding_restores_stock(self):
        stock_before = get_current_stock(self.product)
        sale = self._sell()
        document = sale.documents.first()

        void_document(document, reason="x", pin="1234", performed_by=self.seller)

        self.assertEqual(get_current_stock(self.product), stock_before)

    def test_voiding_marks_sale_and_document_voided(self):
        sale = self._sell()
        document = sale.documents.first()

        voided_document, _credit_note = void_document(
            document, reason="x", pin="1234", performed_by=self.seller
        )

        sale.refresh_from_db()
        self.assertTrue(sale.is_voided)
        self.assertEqual(voided_document.status, DocumentStatus.VOIDED)

    def test_voiding_issues_credit_note_referencing_original(self):
        sale = self._sell()
        document = sale.documents.first()

        _voided_document, credit_note = void_document(
            document, reason="x", pin="1234", performed_by=self.seller
        )

        self.assertEqual(credit_note.document_type, DocumentType.NOTA_CREDITO)
        self.assertEqual(credit_note.related_document, document)
        self.assertEqual(credit_note.total, document.total)
        self.assertEqual(credit_note.series, "NC01")
        self.assertEqual(credit_note.correlativo, 1)

    def test_cannot_void_already_voided_document(self):
        sale = self._sell()
        document = sale.documents.first()
        void_document(document, reason="x", pin="1234", performed_by=self.seller)
        document.refresh_from_db()

        with self.assertRaises(DocumentNotVoidableError):
            void_document(document, reason="x", pin="1234", performed_by=self.seller)

    def test_cannot_void_non_nota_venta(self):
        sale = self._sell()
        document = sale.documents.first()
        document.document_type = DocumentType.BOLETA
        document.save()

        with self.assertRaises(DocumentNotVoidableError):
            void_document(document, reason="x", pin="1234", performed_by=self.seller)


class AdminPinTests(TestCase):
    def test_find_by_pin_matches_correct_admin(self):
        admin1 = User.objects.create_user(username="a1", password="x", is_staff=True)
        admin2 = User.objects.create_user(username="a2", password="x", is_staff=True)
        AdminPin.get_or_create_for(admin1).set_pin("1111")
        AdminPin.get_or_create_for(admin2).set_pin("2222")

        self.assertEqual(AdminPin.find_by_pin("1111"), admin1)
        self.assertEqual(AdminPin.find_by_pin("2222"), admin2)
        self.assertIsNone(AdminPin.find_by_pin("9999"))

    def test_changing_one_pin_does_not_affect_another(self):
        admin1 = User.objects.create_user(username="a1", password="x", is_staff=True)
        admin2 = User.objects.create_user(username="a2", password="x", is_staff=True)
        AdminPin.get_or_create_for(admin1).set_pin("1111")
        AdminPin.get_or_create_for(admin2).set_pin("2222")

        AdminPin.get_or_create_for(admin1).set_pin("3333")

        self.assertIsNone(AdminPin.find_by_pin("1111"))
        self.assertEqual(AdminPin.find_by_pin("3333"), admin1)
        self.assertEqual(AdminPin.find_by_pin("2222"), admin2)
