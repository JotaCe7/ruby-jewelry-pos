from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class NamedCatalogModel(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self):
        return self.name


class Gender(models.TextChoices):
    MALE = "M", _("Male")
    FEMALE = "F", _("Female")
    OTHER = "O", _("Other")


class DocumentType(models.TextChoices):
    DNI = "DNI", _("DNI")
    CE = "CE", _("Foreign Resident Card")


class UserProfile(TimeStampedModel):
    # Extends Django's built-in User with the extra fields this business
    # wants on file for Admin/Vendedor accounts, without swapping
    # AUTH_USER_MODEL — too risky to introduce this deep into a live
    # project (every existing FK to User, and the users table itself,
    # would need migrating). A one-to-one side table is additive instead.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    phone = models.CharField(max_length=20, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    document_type = models.CharField(max_length=3, choices=DocumentType.choices, blank=True)
    document_number = models.CharField(max_length=20, blank=True)
    hire_date = models.DateField(null=True, blank=True)
    address = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = _("user profile")
        verbose_name_plural = _("user profiles")

    def __str__(self):
        return self.user.username


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    # Guarantees every User has a profile regardless of entry point
    # (this API, Django admin, `createsuperuser`, the shell) — the same
    # "can't drift no matter who creates it" reasoning as
    # PaymentMethod.is_default's own save() override.
    if created:
        UserProfile.objects.get_or_create(user=instance)
