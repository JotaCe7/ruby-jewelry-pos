from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel


class Contact(TimeStampedModel):
    name = models.CharField(max_length=150)
    tax_id = models.CharField(_("tax ID"), max_length=20, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self):
        return self.name


class Supplier(Contact):
    class Meta:
        verbose_name = _("supplier")
        verbose_name_plural = _("suppliers")


class CustomerDocumentType(models.TextChoices):
    """SUNAT's identity-document catalog (Catálogo 06), narrowed to the
    values retail actually sees. A Factura requires RUC, a Boleta accepts
    any of the others or none at all."""

    DNI = "DNI", _("DNI")
    RUC = "RUC", _("RUC")
    CE = "CE", _("Foreign Resident Card")
    PASSPORT = "PASAPORTE", _("Passport")
    NO_DOCUMENT = "SIN_DOCUMENTO", _("No document")


class Customer(Contact):
    document_type = models.CharField(
        max_length=15, choices=CustomerDocumentType.choices, default=CustomerDocumentType.NO_DOCUMENT
    )

    class Meta:
        verbose_name = _("customer")
        verbose_name_plural = _("customers")
