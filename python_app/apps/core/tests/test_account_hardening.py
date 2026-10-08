from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import serializers
from rest_framework.test import APITestCase

from apps.core.forms import ResearcherUserChangeForm
from apps.core.throttling import LoginAccountThrottle, LoginIPThrottle
from apps.core.views.auth import ResearcherRegistrationSerializer


class AccountEmailConstraintTests(TestCase):
    def test_database_rejects_case_and_space_variants(self):
        user = get_user_model()
        user.objects.create(username="first", email="reader@example.test")
        for email in ["READER@example.test", " reader@example.test "]:
            with self.subTest(email=email), self.assertRaises(IntegrityError), transaction.atomic():
                user.objects.create(username="duplicate", email=email)

    def test_blank_emails_are_allowed_for_system_accounts(self):
        user = get_user_model()
        user.objects.create(username="first", email="")
        user.objects.create(username="second", email="")

    def test_registration_race_reports_email_not_username(self):
        serializer = ResearcherRegistrationSerializer(data={
            "username": "new-reader", "email": "reader@example.test",
            "password": "Long-Independent-Pass-8391!",
            "password_confirmation": "Long-Independent-Pass-8391!",
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        get_user_model().objects.create(username="won-race", email="READER@example.test")
        with self.assertRaises(serializers.ValidationError) as raised:
            serializer.save()
        self.assertIn("email", raised.exception.detail)
        self.assertFalse(get_user_model().objects.filter(username="new-reader").exists())

    def test_admin_email_validation_excludes_current_user(self):
        user = get_user_model().objects.create(username="reader", email="reader@example.test")
        form = ResearcherUserChangeForm(instance=user)
        form.cleaned_data = {"email": " READER@example.test "}
        self.assertEqual(form.clean_email(), "reader@example.test")
        form.instance = get_user_model()(username="someone-else")
        with self.assertRaises(ValidationError):
            form.clean_email()


class LoginThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.ip_rate = patch.object(LoginIPThrottle, "get_rate", return_value="2/min")
        self.account_rate = patch.object(LoginAccountThrottle, "get_rate", return_value="2/min")
        self.ip_rate.start()
        self.account_rate.start()
        self.addCleanup(self.ip_rate.stop)
        self.addCleanup(self.account_rate.stop)

    def post_login(self, username, ip="192.0.2.1"):
        return self.client.post("/api/v1/auth/session/", {
            "username": username, "password": "incorrect-password",
        }, format="json", REMOTE_ADDR=ip)

    @patch("apps.core.views.auth.authenticate", return_value=None)
    def test_ip_limit_prevents_password_work_and_returns_retry_after(self, authenticate):
        self.assertEqual(self.post_login("one").status_code, 401)
        self.assertEqual(self.post_login("two").status_code, 401)
        response = self.post_login("three")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["error"]["code"], "RATE_LIMITED")
        self.assertIn("Retry-After", response)
        self.assertEqual(authenticate.call_count, 2)

    @patch("apps.core.views.auth.authenticate", return_value=None)
    def test_account_limit_is_normalized_across_ips(self, authenticate):
        self.assertEqual(self.post_login("reader", "192.0.2.1").status_code, 401)
        self.assertEqual(self.post_login("READER", "192.0.2.2").status_code, 401)
        self.assertEqual(self.post_login(" reader ", "192.0.2.3").status_code, 429)
        self.assertEqual(authenticate.call_count, 2)

    @patch("apps.core.views.auth.authenticate", return_value=None)
    def test_session_reads_and_logout_remain_available_after_limit(self, authenticate):
        for _ in range(3):
            self.post_login("reader")
        self.assertEqual(self.client.get("/api/v1/auth/session/").status_code, 200)
        self.assertEqual(self.client.delete("/api/v1/auth/session/").status_code, 204)

    def test_valid_login_still_creates_session(self):
        get_user_model().objects.create_user(username="reader", password="valid-pass-8123")
        response = self.client.post("/api/v1/auth/session/", {
            "username": "reader", "password": "valid-pass-8123",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["authenticated"])
