from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, DataSource, SourceRelease
from apps.core.services.external_analysis import query_string_physical_network
from apps.core.tasks import run_external_analysis_task


class ExternalAnalysisApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="external-owner", password="test-password-123")
        self.other = user_model.objects.create_user(username="external-other", password="test-password-123")
        self.client.force_authenticate(self.owner)

    @patch("apps.core.tasks.run_external_analysis_task.apply_async")
    def test_reactome_enrichment_is_explicitly_opt_in_and_queued_as_private_task(self, enqueue):
        rejected = self.client.post(
            reverse("pathway-enrichment"),
            {"targets": ["TP53", "IL6"], "consent": False}, format="json",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(AnalysisTask.objects.count(), 0)

        response = self.client.post(
            reverse("pathway-enrichment"),
            {"targets": ["TP53", "IL6"], "consent": True}, format="json",
        )
        self.assertEqual(response.status_code, 202)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(task.owner, self.owner)
        self.assertEqual(task.status, AnalysisTask.Status.QUEUED)
        self.assertTrue(task.input_parameters["consentRecorded"])
        enqueue.assert_called_once_with(args=[task.pk])

        self.client.force_authenticate(self.other)
        private_response = self.client.get(reverse("analysis-task-detail", args=[task.pk]))
        self.assertEqual(private_response.status_code, 404)

    @patch("apps.core.tasks.run_external_analysis_task.apply_async")
    def test_string_request_is_limited_and_queued_without_exceeding_provider_cap(self, enqueue):
        too_many = self.client.post(
            reverse("string-network"),
            {"targets": [f"GENE{i}" for i in range(201)], "consent": True}, format="json",
        )
        self.assertEqual(too_many.status_code, 400)
        self.assertEqual(AnalysisTask.objects.count(), 0)

        response = self.client.post(
            reverse("string-network"),
            {"targets": ["TP53", "IL6"], "consent": True, "required_score": 850}, format="json",
        )
        self.assertEqual(response.status_code, 202)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(task.input_parameters["requiredScore"], 850)
        self.assertEqual(task.input_parameters["networkType"], "physical")
        enqueue.assert_called_once_with(args=[task.pk])


class ExternalAnalysisWorkerTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="external-worker", password="test-password-123")
        self.source = DataSource.objects.create(slug="string", name="STRING")
        self.release = SourceRelease.objects.create(source=self.source, version="fixture-v1")

    @patch("apps.core.services.external_analysis._request_string_network")
    @override_settings(STRING_DB_VERSION="fixture-v1")
    def test_string_worker_persists_network_and_source_version(self, request_network):
        request_network.return_value = [{
            "stringId_A": "9606.ENSP0001",
            "stringId_B": "9606.ENSP0002",
            "preferredName_A": "TP53",
            "preferredName_B": "IL6",
            "score": 0.91,
        }]
        task = AnalysisTask.objects.create(
            owner=self.user,
            created_by=self.user,
            task_type=AnalysisTask.TaskType.NETWORK,
            status=AnalysisTask.Status.QUEUED,
            input_parameters={
                "analysisKind": "string_ppi",
                "rawTargets": ["TP53", "IL6"],
                "requiredScore": 700,
            },
        )

        outcome = run_external_analysis_task.run(task.pk)
        task.refresh_from_db()

        self.assertEqual(outcome["status"], AnalysisTask.Status.SUCCEEDED)
        self.assertEqual(task.result["interactionCount"], 1)
        self.assertEqual(task.result["edges"][0]["scoreOutOf1000"], 910)
        self.assertEqual(list(task.source_releases.all()), [self.release])


class ProteomicsStringConnectorTests(SimpleTestCase):
    @patch("apps.core.services.external_analysis._run_string")
    def test_proteomics_connector_deduplicates_and_preserves_physical_network_result(self, run_string):
        expected = {"networkType": "physical", "interactionCount": 1}
        run_string.return_value = (expected, "fixture-v1")

        result = query_string_physical_network([" TP53 ", "IL6", "TP53"], 800)

        self.assertEqual(result, (expected, "fixture-v1"))
        run_string.assert_called_once_with(["TP53", "IL6"], 800)

    @patch("apps.core.services.external_analysis._run_string")
    def test_proteomics_connector_rejects_unbounded_or_invalid_queries_before_network_call(self, run_string):
        with self.assertRaises(ValueError):
            query_string_physical_network([f"GENE{i}" for i in range(201)], 700)
        with self.assertRaises(ValueError):
            query_string_physical_network(["TP53", "IL6"], -1)
        with self.assertRaises(ValueError):
            query_string_physical_network(["TP53", "IL6"], 1001)
        with self.assertRaises(ValueError):
            query_string_physical_network(["TP53", "TP53"], 700)

        run_string.assert_not_called()
