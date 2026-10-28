"""Exercise real cookies/CSRF and Vite's changed Host, not force_authenticate."""
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease
from config.local_security import LOCAL_FRONTEND_ORIGINS, trusted_csrf_origins


class LocalCsrfConfigurationTests(SimpleTestCase):
    def test_loopback_frontend_defaults_only_apply_in_development(self):
        self.assertEqual(trusted_csrf_origins([], debug=True), list(LOCAL_FRONTEND_ORIGINS))
        self.assertEqual(trusted_csrf_origins([], debug=False), [])
        self.assertEqual(set(LOCAL_FRONTEND_ORIGINS), {"http://127.0.0.1:5173", "http://localhost:5173"})
        self.assertTrue(all("*" not in origin for origin in LOCAL_FRONTEND_ORIGINS))

    def test_explicit_deployment_origins_are_not_broadened_or_mutated(self):
        configured = ["https://research.example.test"]
        for debug in [True, False]:
            self.assertEqual(trusted_csrf_origins(configured, debug=debug), configured)
        self.assertEqual(configured, ["https://research.example.test"])


@override_settings(CSRF_TRUSTED_ORIGINS=trusted_csrf_origins([], debug=True))
class LocalProxyCsrfWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username="csrf-workflow-owner", password="synthetic-pass-123")
        source = DataSource.objects.create(slug="csrf-workflow", name="合成 CSRF 测试来源")
        release = SourceRelease.objects.create(source=source, version="v1")
        herb, compound, target, disease = [KnowledgeEntity.objects.create(
            entity_type=kind, stable_id=f"csrf:{kind}", label=label, source_release=release
        ) for kind, label in [("herb", "黄芩"), ("compound", "合成成分"), ("protein", "TP53"), ("disease", "Pulmonary fibrosis")]]
        for index, (kind, subject, object_) in enumerate([
            ("contains", herb, compound), ("targets", compound, target), ("disease_target", disease, target),
        ]):
            EvidenceRelation.objects.create(source_release=release, source_record_id=f"csrf:{index}",
                subject=subject, object=object_, relation_type=kind, evidence_type="synthetic")

    def token(self, client):
        return client.get(reverse("auth-csrf"), HTTP_HOST="127.0.0.1:8020").json()["csrfToken"]

    def request(self, client, *, origin="http://127.0.0.1:5173", token=None):
        headers = {"HTTP_HOST": "127.0.0.1:8020", "HTTP_ORIGIN": origin}
        if token is not None:
            headers["HTTP_X_CSRFTOKEN"] = token
        return client.post(reverse("network-pharmacology"), {"herb": "黄芩", "disease": "肺纤维化"},
            content_type="application/json", **headers)

    def test_real_login_then_herb_search_and_intersection_through_proxy_origin(self):
        client = Client(enforce_csrf_checks=True)
        login = client.post(reverse("auth-session"), {"username": self.owner.username, "password": "synthetic-pass-123"},
            content_type="application/json", HTTP_HOST="127.0.0.1:8020", HTTP_ORIGIN="http://127.0.0.1:5173",
            HTTP_X_CSRFTOKEN=self.token(client))
        self.assertEqual(login.status_code, 200, login.content)
        self.assertTrue(login.json()["authenticated"])
        herb = client.post(reverse("batch-herb-evidence"), {"queryType": "herb", "queries": ["黄芩"]},
            content_type="application/json", HTTP_HOST="127.0.0.1:8020", HTTP_ORIGIN="http://127.0.0.1:5173",
            HTTP_X_CSRFTOKEN=self.token(client))
        self.assertEqual(herb.status_code, 200, herb.content)
        self.assertEqual(herb.json()["results"][0]["targets"][0]["label"], "TP53")
        network = self.request(client, token=self.token(client))
        self.assertEqual(network.status_code, 200, network.content)
        self.assertEqual(network.json()["summary"]["strictIntersectionCount"], 1)
        self.assertEqual(AnalysisTask.objects.count(), 1)

    def test_localhost_frontend_origin_is_accepted_with_valid_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(self.request(client, origin="http://localhost:5173", token=self.token(client)).status_code, 200)

    def test_missing_or_incorrect_csrf_token_is_still_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.token(client)
        for token in [None, "a" * 64]:
            response = self.request(client, token=token)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], "CSRF_FAILED")
        self.assertEqual(AnalysisTask.objects.count(), 0)

    def test_other_origins_are_rejected_even_with_valid_cookie_and_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for origin in ["https://untrusted.example.test", "http://127.0.0.1:5174", "http://localhost:8080"]:
            response = self.request(client, origin=origin, token=self.token(client))
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], "CSRF_FAILED")
        self.assertEqual(AnalysisTask.objects.count(), 0)

    def test_previous_empty_origin_configuration_reproduces_the_reported_failure(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        with override_settings(CSRF_TRUSTED_ORIGINS=[]):
            response = self.request(client, token=self.token(client))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "CSRF_FAILED")
        self.assertEqual(AnalysisTask.objects.count(), 0)
