from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import DocumentType, Gender, UserProfile

User = get_user_model()


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
