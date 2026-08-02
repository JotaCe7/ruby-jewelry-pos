from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import UserProfile

User = get_user_model()


class UserProfileSignalTests(TestCase):
    def test_creating_a_user_automatically_creates_a_profile(self):
        user = User.objects.create_user(username="new_seller", password="x")
        self.assertTrue(UserProfile.objects.filter(user=user).exists())


class UserAccountApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin1", password="x", is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_admin_can_create_a_vendedor_with_profile_fields(self):
        response = self.client.post(
            "/api/core/users/",
            {
                "username": "vendedora1",
                "password": "a-real-password-123",
                "first_name": "Ana",
                "phone": "999888777",
                "birth_date": "1995-05-20",
                "gender": "F",
                "document_type": "DNI",
                "document_number": "12345678",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn("password", response.data)

        created = User.objects.get(username="vendedora1")
        self.assertFalse(created.is_staff)
        self.assertTrue(created.check_password("a-real-password-123"))
        self.assertEqual(created.profile.phone, "999888777")
        self.assertEqual(created.profile.gender, "F")

    def test_creating_without_a_password_is_rejected(self):
        response = self.client.post("/api/core/users/", {"username": "no_password_user"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="no_password_user").exists())

    def test_updating_without_a_password_does_not_change_the_existing_one(self):
        seller = User.objects.create_user(username="seller1", password="original-pw")
        response = self.client.patch(
            f"/api/core/users/{seller.id}/", {"phone": "111222333"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        seller.refresh_from_db()
        self.assertTrue(seller.check_password("original-pw"))
        self.assertEqual(seller.profile.phone, "111222333")

    def test_delete_is_not_allowed_users_are_deactivated_not_removed(self):
        seller = User.objects.create_user(username="seller2", password="x")
        response = self.client.delete(f"/api/core/users/{seller.id}/")
        self.assertEqual(response.status_code, 405)
        self.assertTrue(User.objects.filter(username="seller2").exists())

    def test_vendedor_cannot_access_user_management(self):
        vendedor = User.objects.create_user(username="vendedor1", password="x", is_staff=False)
        client = APIClient()
        client.force_authenticate(user=vendedor)
        response = client.get("/api/core/users/")
        self.assertEqual(response.status_code, 403)

    def test_profile_fields_are_optional_outside_production(self):
        # ENVIRONMENT defaults to "dev" when not overridden below — this
        # documents that default rather than depending on it silently.
        response = self.client.post(
            "/api/core/users/", {"username": "bare_user", "password": "x123456789"}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    @override_settings(ENVIRONMENT="production")
    def test_profile_fields_are_required_in_production(self):
        response = self.client.post(
            "/api/core/users/", {"username": "bare_user", "password": "x123456789"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        for field in [
            "phone",
            "birth_date",
            "gender",
            "document_type",
            "document_number",
            "hire_date",
            "address",
        ]:
            self.assertIn(field, response.data)
        self.assertFalse(User.objects.filter(username="bare_user").exists())

    @override_settings(ENVIRONMENT="production")
    def test_complete_profile_is_accepted_in_production(self):
        response = self.client.post(
            "/api/core/users/",
            {
                "username": "complete_user",
                "password": "x123456789",
                "phone": "999888777",
                "birth_date": "1990-01-01",
                "gender": "M",
                "document_type": "DNI",
                "document_number": "87654321",
                "hire_date": "2026-01-01",
                "address": "Av. Siempre Viva 123",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    @override_settings(ENVIRONMENT="production")
    def test_editing_a_legacy_incomplete_profile_still_requires_completing_it(self):
        # A user created before this rule existed has a blank profile —
        # any edit in production still has to satisfy the requirement
        # (using the *existing* saved value for fields not touched by
        # this particular request), rather than being grandfathered in
        # forever. Intentional: it nudges incomplete legacy records
        # toward completion instead of letting them stay incomplete.
        seller = User.objects.create_user(username="legacy_seller", password="x")
        response = self.client.patch(
            f"/api/core/users/{seller.id}/", {"email": "legacy@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("phone", response.data)

    @override_settings(ENVIRONMENT="production")
    def test_editing_an_already_complete_profile_for_an_unrelated_field_succeeds(self):
        seller = User.objects.create_user(username="complete_seller", password="x")
        UserProfile.objects.filter(user=seller).update(
            phone="999888777",
            birth_date="1990-01-01",
            gender="M",
            document_type="DNI",
            document_number="87654321",
            hire_date="2026-01-01",
            address="Av. Siempre Viva 123",
        )
        response = self.client.patch(
            f"/api/core/users/{seller.id}/", {"email": "complete@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
