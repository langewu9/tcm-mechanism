from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, DataSource, SourceRelease
from apps.core.services.external_analysis import calculate_unweighted_betweenness, query_string_physical_network
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
        self.source, _ = DataSource.objects.get_or_create(
            slug="string",
            defaults={"name": "STRING", "access_mode": DataSource.AccessMode.API},
        )
        self.source.enabled = True
        self.source.save(update_fields=["enabled"])
        self.release, _ = SourceRelease.objects.get_or_create(source=self.source, version="12.0")

    @patch("apps.core.services.external_analysis._request_string_network")
    @override_settings(STRING_DB_VERSION="12.0")
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
        self.assertEqual(task.result["nodes"][0]["degree"], 1)
        self.assertEqual(task.result["nodes"][0]["betweenness"], 0.0)
        self.assertEqual(
            task.result["centralityMethod"],
            "degree=unique_neighbors; betweenness=normalized_unweighted_brandes",
        )
        self.assertEqual(task.result["sourceEndpoint"], "https://version-12-0.string-db.org/api")
        self.assertEqual(list(task.source_releases.all()), [self.release])

    @patch("apps.core.services.external_analysis._request_string_network")
    @override_settings(STRING_DB_VERSION="12.0")
    def test_string_worker_respects_administrator_disable_switch(self, request_network):
        self.source.enabled = False
        self.source.save(update_fields=["enabled"])
        task = AnalysisTask.objects.create(
            owner=self.user,
            created_by=self.user,
            task_type=AnalysisTask.TaskType.NETWORK,
            status=AnalysisTask.Status.QUEUED,
            input_parameters={
                "analysisKind": "string_ppi",
                "rawTargets": ["TP53", "MDM2"],
                "requiredScore": 700,
                "consentRecorded": True,
            },
        )

        outcome = run_external_analysis_task.run(task.pk)
        task.refresh_from_db()

        self.assertEqual(outcome["status"], AnalysisTask.Status.FAILED)
        self.assertIn("已停用", task.error_summary)
        request_network.assert_not_called()


class StringVersionResolutionTests(SimpleTestCase):
    @override_settings(STRING_DB_VERSION="12.0")
    @patch("apps.core.services.external_analysis._open_string")
    def test_explicit_string_version_uses_version_specific_endpoint_without_network_discovery(self, open_string):
        from apps.core.services.external_analysis import _string_api_release

        self.assertEqual(
            _string_api_release(),
            ("12.0", "https://version-12-0.string-db.org/api", False),
        )
        open_string.assert_not_called()

    @patch("apps.core.services.external_analysis._open_string")
    def test_discovers_current_string_version_and_builds_pinned_endpoint(self, open_string):
        from apps.core.services.external_analysis import _string_api_release

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b'[{"string_version":"12.5","stable_address":"https://string-db.org"}]'

        open_string.return_value = Response()
        version, endpoint, discovered = _string_api_release()

        self.assertEqual(version, "12.5")
        self.assertEqual(endpoint, "https://version-12-5.string-db.org/api")
        self.assertTrue(discovered)

    @patch("apps.core.services.external_analysis._open_string")
    def test_rejects_untrusted_string_version_endpoint(self, open_string):
        from apps.core.services.external_analysis import ExternalAnalysisError, _string_api_release

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b'[{"string_version":"12.5","stable_address":"https://attacker.example"}]'

        open_string.return_value = Response()
        with self.assertRaises(ExternalAnalysisError):
            _string_api_release()


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


class StringCentralityTests(SimpleTestCase):
    def test_normalized_betweenness_on_a_path_graph(self):
        centrality = calculate_unweighted_betweenness(
            ["a", "b", "c"],
            [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
        )

        self.assertEqual(centrality["a"], {"degree": 1, "betweenness": 0.0})
        self.assertEqual(centrality["b"], {"degree": 2, "betweenness": 1.0})
        self.assertEqual(centrality["c"], {"degree": 1, "betweenness": 0.0})

    def test_equal_shortest_paths_split_betweenness_and_duplicate_edges_do_not_inflate_degree(self):
        edges = [
            {"source": "a", "target": "b"},
            {"source": "a", "target": "c"},
            {"source": "b", "target": "d"},
            {"source": "c", "target": "d"},
            {"source": "a", "target": "b"},
            {"source": "a", "target": "a"},
            {"source": "unknown", "target": "d"},
        ]

        centrality = calculate_unweighted_betweenness(["a", "b", "c", "d"], edges)

        self.assertEqual(centrality["a"]["degree"], 2)
        self.assertEqual(centrality["b"]["degree"], 2)
        self.assertAlmostEqual(centrality["b"]["betweenness"], 1 / 6, places=6)
        self.assertAlmostEqual(centrality["c"]["betweenness"], 1 / 6, places=6)


class StringResponseBoundsTests(SimpleTestCase):
    @patch("apps.core.services.external_analysis._open_string")
    def test_string_network_response_is_read_with_a_fixed_byte_limit(self, open_string):
        from apps.core.services.external_analysis import (
            ExternalAnalysisError,
            MAX_STRING_RESPONSE_BYTES,
            _request_string_network,
        )

        class OversizedResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, limit):
                self.limit = limit
                return b"x" * limit

        response = OversizedResponse()
        open_string.return_value = response
        with self.assertRaisesRegex(ExternalAnalysisError, "超过安全大小限制"):
            _request_string_network(["TP53", "IL6"], 700, "https://version-12-5.string-db.org/api", False)
        self.assertEqual(response.limit, MAX_STRING_RESPONSE_BYTES + 1)
