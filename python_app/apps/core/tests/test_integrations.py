from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask


class IntegrationMonitorApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_superuser(
            username="integration-admin", email="admin@example.test", password="test-password-123"
        )
        self.researcher = user_model.objects.create_user(
            username="integration-researcher", password="test-password-123"
        )
        self.status_url = reverse("admin-integration-status")
        self.test_url = reverse("admin-integration-test")

    def test_status_and_test_require_platform_superuser(self):
        self.assertEqual(reverse("admin:index"), "/django-admin/")
        self.assertEqual(self.client.get(self.status_url).status_code, 401)
        self.client.force_authenticate(self.researcher)
        self.assertEqual(self.client.get(self.status_url).status_code, 403)
        self.assertEqual(self.client.post(self.test_url, {"target": "compare"}, format="json").status_code, 403)

    def test_status_reports_django_catalog_and_redacted_model_configuration(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.status_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data["services"]), {"health", "sources", "qwenStatus", "qwenModels"})
        self.assertEqual(response.data["services"]["health"]["data"]["api"], "Django")
        self.assertEqual(response.data["services"]["health"]["data"]["database"], "ok")
        self.assertNotIn("apiKey", response.data)
        self.assertNotIn("CASE_MODEL_API_KEY", str(response.data))

    def test_main_local_catalog_and_comparison_checks_use_current_django_services(self):
        self.client.force_authenticate(self.admin)
        for target in ("disease", "herb", "component", "intersection", "compare"):
            with self.subTest(target=target):
                response = self.client.post(self.test_url, {"target": target}, format="json")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["target"], target)
                self.assertTrue(response.data["result"]["ok"])
                self.assertEqual(response.data["result"]["status"], 200)
        self.assertEqual(AnalysisTask.objects.count(), 0)

    @patch("apps.core.views.integrations._test_model_connection")
    def test_model_connection_test_requires_per_request_consent(self, test_model):
        self.client.force_authenticate(self.admin)
        denied = self.client.post(self.test_url, {"target": "qwen"}, format="json")
        self.assertEqual(denied.status_code, 400)
        test_model.assert_not_called()

        test_model.return_value = (True, 200, {"model": "local-model", "version": "v1"}, None)
        allowed = self.client.post(self.test_url, {"target": "qwen", "consent": True}, format="json")
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(allowed.data["result"]["ok"])
        test_model.assert_called_once()

    @patch("apps.core.views.integrations.search_molecules")
    def test_chembl_check_requires_consent_and_only_sends_fixed_demo_query(self, search):
        self.client.force_authenticate(self.admin)
        denied = self.client.post(self.test_url, {"target": "chembl"}, format="json")
        self.assertEqual(denied.status_code, 400)
        search.assert_not_called()

        search.return_value = {"source": "ChEMBL", "totalCount": 0, "results": []}
        allowed = self.client.post(self.test_url, {"target": "chembl", "consent": True}, format="json")
        self.assertEqual(allowed.status_code, 200)
        search.assert_called_once_with("quercetin")

    def test_ai_scientist_is_reported_as_not_yet_migrated(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(self.test_url, {"target": "scientist"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["result"]["ok"])
        self.assertEqual(response.data["result"]["status"], 501)
        self.assertIn("Excel/SQLite", response.data["result"]["error"])
