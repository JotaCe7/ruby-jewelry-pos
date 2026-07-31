from django.test import TestCase

from .models import PaymentMethod


class PaymentMethodDefaultExclusivityTests(TestCase):
    """PaymentMethod.is_default drives which method auto-preselects on a
    new POS ticket — it must always be exclusive, no matter which entry
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
