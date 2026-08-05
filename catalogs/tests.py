from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import PaymentMethod, ProductCategory, ProductSubcategory

User = get_user_model()


class PaymentMethodDefaultExclusivityTests(TestCase):
    """PaymentMethod.is_default drives which method auto-preselects on a
    new POS ticket. It must always be exclusive, no matter which entry
    point sets it (API, Django admin, or shell), since the model's own
    save() override is what enforces this, not any particular caller."""

    def test_saving_a_new_default_clears_the_previous_one(self):
        efectivo = PaymentMethod.objects.create(name="Efectivo", is_cash=True, is_default=True)
        caja = PaymentMethod.objects.create(name="Caja", is_cash=False)

        caja.is_default = True
        caja.save()

        efectivo.refresh_from_db()
        self.assertFalse(efectivo.is_default)
        self.assertTrue(caja.is_default)

    def test_only_one_method_is_default_after_multiple_switches(self):
        a = PaymentMethod.objects.create(name="A", is_default=True)
        b = PaymentMethod.objects.create(name="B")
        c = PaymentMethod.objects.create(name="C")

        b.is_default = True
        b.save()
        c.is_default = True
        c.save()

        self.assertEqual(PaymentMethod.objects.filter(is_default=True).count(), 1)
        self.assertEqual(PaymentMethod.objects.get(is_default=True), c)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertFalse(a.is_default)
        self.assertFalse(b.is_default)

    def test_saving_without_default_does_not_disturb_existing_default(self):
        efectivo = PaymentMethod.objects.create(name="Efectivo", is_default=True)
        caja = PaymentMethod.objects.create(name="Caja")

        caja.name = "Caja Renombrada"
        caja.save()

        efectivo.refresh_from_db()
        self.assertTrue(efectivo.is_default)


class HierarchicalCodeTests(TestCase):
    """ProductCategory/ProductSubcategory.code: auto-generated, never
    editable afterward, distinct from `name`, which stays freely
    correctable."""

    def test_categories_get_sequential_2_digit_codes(self):
        earrings = ProductCategory.objects.create(name="Earrings")
        necklaces = ProductCategory.objects.create(name="Necklaces")
        self.assertEqual(earrings.code, "01")
        self.assertEqual(necklaces.code, "02")

    def test_subcategories_are_scoped_to_their_category(self):
        earrings = ProductCategory.objects.create(name="Earrings")
        necklaces = ProductCategory.objects.create(name="Necklaces")
        s5 = ProductSubcategory.objects.create(name="S/5", category=earrings)
        s8 = ProductSubcategory.objects.create(name="S/8", category=earrings)
        # A second category's first subcategory still starts at 01 within
        # its own scope, not continuing the first category's count.
        fine_sub = ProductSubcategory.objects.create(name="Fine", category=necklaces)
        self.assertEqual(s5.code, "0101")
        self.assertEqual(s8.code, "0102")
        self.assertEqual(fine_sub.code, "0201")

    def test_deleting_a_subcategory_never_frees_its_number_for_reuse(self):
        earrings = ProductCategory.objects.create(name="Earrings")
        s5 = ProductSubcategory.objects.create(name="S/5", category=earrings)
        ProductSubcategory.objects.create(name="S/8", category=earrings)
        s5.delete()
        xuping = ProductSubcategory.objects.create(name="Xuping", category=earrings)
        # Count-based numbering would have reused "0101" (now only one
        # sibling remains). MAX-based correctly continues from "0102".
        self.assertEqual(xuping.code, "0103")

    def test_code_cannot_be_changed_via_the_api(self):
        admin = User.objects.create_user(username="admin1", password="x", is_staff=True)
        client = APIClient()
        client.force_authenticate(user=admin)
        earrings = ProductCategory.objects.create(name="Earrings")

        response = client.patch(
            f"/api/catalogs/product-categories/{earrings.id}/", {"code": "99"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.data)
        earrings.refresh_from_db()
        self.assertEqual(earrings.code, "01")


class PreviewCodeTests(TestCase):
    """The create-form preview endpoints must show what a code *would*
    be without ever actually consuming a sequence number. Calling
    preview repeatedly must keep returning the same value until
    something is actually saved."""

    def setUp(self):
        admin = User.objects.create_user(username="admin2", password="x", is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(user=admin)

    def test_category_preview_does_not_consume_the_sequence(self):
        first = self.client.get("/api/catalogs/product-categories/preview_code/")
        second = self.client.get("/api/catalogs/product-categories/preview_code/")
        self.assertEqual(first.data["code"], "01")
        self.assertEqual(second.data["code"], "01")

        ProductCategory.objects.create(name="Earrings")
        third = self.client.get("/api/catalogs/product-categories/preview_code/")
        self.assertEqual(third.data["code"], "02")

    def test_subcategory_preview_does_not_consume_the_sequence(self):
        earrings = ProductCategory.objects.create(name="Earrings")
        response = self.client.get(
            "/api/catalogs/product-subcategories/preview_code/", {"category": earrings.id}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["code"], "0101")

        ProductSubcategory.objects.create(name="S/5", category=earrings)
        response = self.client.get(
            "/api/catalogs/product-subcategories/preview_code/", {"category": earrings.id}
        )
        self.assertEqual(response.data["code"], "0102")
