from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escapejs
from unittest.mock import patch


class AdminDocumentationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.researcher = users.objects.create_user(username="docs-researcher")
        cls.staff = users.objects.create_user(username="docs-staff", is_staff=True)
        cls.staff.user_permissions.add(*Permission.objects.all())
        cls.root = users.objects.create_superuser(username="docs-root", email="docs-root@example.test")

    def test_docs_and_raw_schema_require_platform_superuser(self):
        for user in (None, self.researcher, self.staff):
            if user is None:
                self.client.logout()
            else:
                self.client.force_login(user)
            for name in ("admin:platform-api-docs", "admin:platform-api-schema", "admin:platform-integrations"):
                with self.subTest(user=user, name=name):
                    response = self.client.get(reverse(name))
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response.url.startswith(reverse("admin:login") + "?next="))
                    followed = self.client.get(reverse(name), follow=True)
                    self.assertNotIn(b"openapi:", followed.content)
                    self.assertNotIn(b"SwaggerUIBundle", followed.content)

    def test_old_documentation_urls_only_redirect_to_protected_admin_tools(self):
        for old, target in (("api-docs", "admin:platform-api-docs"), ("api-schema", "admin:platform-api-schema")):
            response = self.client.get(reverse(old), {"format": "json"})
            self.assertRedirects(response, reverse(target), fetch_redirect_response=False)
            self.assertNotIn(b"openapi", response.content)

    def test_superuser_can_view_docs_schema_and_admin_tool_link(self):
        self.client.force_login(self.root)
        home = self.client.get(reverse("admin:index"))
        self.assertContains(home, reverse("admin:platform-api-docs"))
        self.assertContains(home, reverse("admin:platform-integrations"))
        docs = self.client.get(reverse("admin:platform-api-docs"))
        self.assertEqual(docs.status_code, 200)
        self.assertContains(docs, escapejs(reverse("admin:platform-api-schema")))
        schema = self.client.get(reverse("admin:platform-api-schema"))
        self.assertEqual(schema.status_code, 200)
        self.assertIn(b"/api/v1/research/datasets/", schema.content)

    def test_public_business_auth_boundary_is_unchanged(self):
        self.assertEqual(self.client.get('/api/v1/health/').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/research/datasets/').status_code, 401)

    @patch("apps.core.views.integrations._test_model_connection")
    @patch("apps.core.views.integrations.search_molecules")
    def test_monitor_page_renders_existing_checks_without_executing_them(self, chembl, model):
        self.client.force_login(self.root)
        response = self.client.get(reverse("admin:platform-integrations"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("admin-integration-status"))
        self.assertContains(response, reverse("admin-integration-test"))
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'name="consent" required', count=2)
        self.assertContains(response, 'data-local-check="true"', count=5)
        self.assertContains(response, "core/integration_monitor.js")
        self.assertNotContains(response, "CASE_MODEL_API_KEY")
        model.assert_not_called()
        chembl.assert_not_called()

    def test_monitor_page_does_not_execute_post_requests(self):
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(reverse("admin:platform-integrations"), {"target": "qwen"}).status_code, 405)
