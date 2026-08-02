from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import DocumentType, Gender, UserProfile

User = get_user_model()

# Optional everywhere except production — lets staging/dev testing create
# a user without filling in every field, while production keeps a
# complete record for every real employee.
PROFILE_FIELDS_REQUIRED_IN_PRODUCTION = [
    "phone",
    "birth_date",
    "gender",
    "document_type",
    "document_number",
    "hire_date",
    "address",
]


class UserSerializer(serializers.ModelSerializer):
    """Admin-only user management: combines the built-in User with its
    UserProfile side table into one flat read/write shape. Required on
    create, optional on update (leaving it blank never resets a password).
    """

    password = serializers.CharField(
        write_only=True, required=False, style={"input_type": "password"}
    )
    phone = serializers.CharField(source="profile.phone", required=False, allow_blank=True)
    birth_date = serializers.DateField(source="profile.birth_date", required=False, allow_null=True)
    gender = serializers.ChoiceField(
        source="profile.gender", choices=Gender.choices, required=False, allow_blank=True
    )
    document_type = serializers.ChoiceField(
        source="profile.document_type", choices=DocumentType.choices, required=False, allow_blank=True
    )
    document_number = serializers.CharField(
        source="profile.document_number", required=False, allow_blank=True
    )
    hire_date = serializers.DateField(source="profile.hire_date", required=False, allow_null=True)
    address = serializers.CharField(source="profile.address", required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_active",
            "password",
            "phone",
            "birth_date",
            "gender",
            "document_type",
            "document_number",
            "hire_date",
            "address",
        ]

    def validate(self, attrs):
        if settings.ENVIRONMENT != "production":
            return attrs
        profile_data = attrs.get("profile", {})
        existing_profile = getattr(self.instance, "profile", None) if self.instance else None
        errors = {}
        for field in PROFILE_FIELDS_REQUIRED_IN_PRODUCTION:
            # A PATCH that doesn't touch this field falls back to what's
            # already saved, so editing an unrelated field never trips
            # this on a user created before it was required.
            value = profile_data[field] if field in profile_data else getattr(existing_profile, field, None)
            if value in (None, ""):
                errors[field] = _("Obligatorio en producción.")
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def validate_password(self, value):
        if value:
            try:
                django_validate_password(value)
            except DjangoValidationError as exc:
                raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def to_representation(self, instance):
        # Belt-and-suspenders: the post_save signal (core/models.py) and
        # the backfill migration should mean every User already has a
        # profile, but this guards against ever 500ing on this screen if
        # some entry point (shell, a future createsuperuser call) slips
        # through without one.
        UserProfile.objects.get_or_create(user=instance)
        return super().to_representation(instance)

    def create(self, validated_data):
        profile_data = validated_data.pop("profile", {})
        password = validated_data.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": _("Requerido al crear un usuario.")})
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        UserProfile.objects.update_or_create(user=user, defaults=profile_data)
        return user

    def update(self, instance, validated_data):
        profile_data = validated_data.pop("profile", {})
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        if profile_data:
            UserProfile.objects.update_or_create(user=instance, defaults=profile_data)
        return instance
