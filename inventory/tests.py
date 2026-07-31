from decimal import Decimal

from django.test import TestCase

from catalogs.models import ProductCategory, ProductSubcategory
from pos.models import InventoryExit, MovementType, Sale

from .models import InventoryAudit, InventoryEntry, Product
from .services import apply_stock_entry_cost, get_current_stock


def make_product(sku="SKU-1", cost="4.00", price="10.00"):
    category, _ = ProductCategory.objects.get_or_create(name="Aretes")
    subcategory, _ = ProductSubcategory.objects.get_or_create(name="Aretes Tier", category=category)
    return Product.objects.create(
        sku=sku,
        base_model=f"Producto {sku}",
        subcategory=subcategory,
        suggested_price=Decimal(price),
        unit_cost=Decimal(cost),
        min_stock=0,
    )


def make_exit(product, quantity, movement_type=MovementType.SALE):
    sale = Sale.objects.create(date="2026-01-01")
    return InventoryExit.objects.create(
        sale=sale,
        product=product,
        movement_type=movement_type,
        quantity=quantity,
        unit_price_snapshot=product.suggested_price,
        unit_cost_snapshot=product.unit_cost,
        final_price=product.suggested_price * quantity if movement_type == MovementType.SALE else 0,
    )


class StockCalculationTests(TestCase):
    """Regression coverage for the fan-out bug: combining Sum()s over
    entries/audits/exits (sibling reverse relations) in a single
    annotate() JOINs them together and inflates every sum by the other
    tables' row counts. with_stock() and get_current_stock() both use
    independent Subqueries instead — these tests exercise exactly the
    "more than one row on more than one side" shape that would expose a
    regression back to the naive combined-Sum() approach."""

    def test_stock_nets_entries_audits_and_exits_with_multiple_rows_each(self):
        product = make_product()
        InventoryEntry.objects.create(date="2026-01-01", product=product, quantity=20)
        InventoryEntry.objects.create(date="2026-01-02", product=product, quantity=10)
        make_exit(product, 3)
        make_exit(product, 2)
        InventoryAudit.objects.create(
            date="2026-01-03",
            product=product,
            physical_count=20,
            theoretical_stock_snapshot=25,
            loss_adjustment=5,
            loss_value=Decimal("20.00"),
        )

        # entries(20+10) - audit_loss(5) - exits(3+2) = 20
        self.assertEqual(get_current_stock(product), 20)
        annotated = Product.objects.with_stock().get(pk=product.pk)
        self.assertEqual(annotated.current_stock, 20)

    def test_stock_is_zero_with_no_movements(self):
        product = make_product()
        self.assertEqual(get_current_stock(product), 0)

    def test_with_stock_matches_get_current_stock_for_every_row(self):
        product1 = make_product(sku="A")
        product2 = make_product(sku="B")
        InventoryEntry.objects.create(date="2026-01-01", product=product1, quantity=15)
        InventoryEntry.objects.create(date="2026-01-01", product=product2, quantity=8)
        make_exit(product1, 4)

        annotated = {p.pk: p.current_stock for p in Product.objects.with_stock()}

        self.assertEqual(annotated[product1.pk], get_current_stock(product1))
        self.assertEqual(annotated[product2.pk], get_current_stock(product2))


class WeightedAverageCostTests(TestCase):
    def test_first_entry_with_cost_sets_unit_cost_directly(self):
        product = make_product(cost="0.00")
        apply_stock_entry_cost(product, stock_before=0, entry_quantity=10, entry_unit_cost=Decimal("4.00"))
        product.refresh_from_db()
        self.assertEqual(product.unit_cost, Decimal("4.00"))

    def test_second_entry_averages_weighted_by_quantity(self):
        product = make_product(cost="4.00")
        # 10 units already in stock @ 4.00, adding 10 more @ 6.00
        # -> (10*4.00 + 10*6.00) / 20 = 5.00
        apply_stock_entry_cost(product, stock_before=10, entry_quantity=10, entry_unit_cost=Decimal("6.00"))
        product.refresh_from_db()
        self.assertEqual(product.unit_cost, Decimal("5.00"))

    def test_entry_without_cost_is_a_noop_for_average(self):
        product = make_product(cost="4.00")
        # A caller that skips calling this entirely (no unit_cost given)
        # must leave the running average untouched — nothing to assert on
        # apply_stock_entry_cost itself here beyond documenting the
        # convention, since it's the *caller's* job to skip the call.
        InventoryEntry.objects.create(date="2026-01-01", product=product, quantity=10, unit_cost=None)
        product.refresh_from_db()
        self.assertEqual(product.unit_cost, Decimal("4.00"))


class InventoryAuditApiTests(TestCase):
    def test_audit_computes_theoretical_stock_and_loss_value_from_current_state(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        User = get_user_model()
        admin = User.objects.create_user(username="admin1", password="x", is_staff=True)
        product = make_product(cost="4.00")
        InventoryEntry.objects.create(date="2026-01-01", product=product, quantity=20)

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.post(
            "/api/inventory/audits/",
            {"date": "2026-01-05", "product": product.id, "physical_count": 18},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["theoretical_stock_snapshot"], 20)
        self.assertEqual(response.data["loss_adjustment"], 2)
        self.assertEqual(Decimal(response.data["loss_value"]), Decimal("8.00"))  # 2 * cost(4.00)
        # The shrinkage is netted directly in the stock formula — no
        # compensating InventoryExit row is created for it.
        self.assertEqual(get_current_stock(product), 18)
