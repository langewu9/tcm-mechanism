from copy import deepcopy
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django.urls import reverse
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, DataSource, MedicalCase, ResearchDataset, SourceRelease
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


class ExternalAnalysisProvenanceTests(APITestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username="provenance-owner", password="test-password-123")
        self.other = users.objects.create_user(username="provenance-other", password="test-password-123")
        self.admin = users.objects.create_superuser(username="provenance-admin", password="test-password-123")
        self.case = MedicalCase.objects.create(
            owner=self.owner, title="合成医案", deidentified_text="合成脱敏症状", source_reference="fixture-case",
        )
        self.dataset = ResearchDataset.objects.create(owner=self.owner, name="合成来源表")
        source = DataSource.objects.create(slug="parent-fixture", name="合成来源", access_mode="manual")
        self.release = SourceRelease.objects.create(source=source, version="fixture-v1", checksum_sha256="f" * 64)
        self.parent = AnalysisTask.objects.create(
            owner=self.owner,
            created_by=self.owner,
            task_type=AnalysisTask.TaskType.NETWORK,
            status=AnalysisTask.Status.SUCCEEDED,
            medical_case=self.case,
            dataset=self.dataset,
            finished_at=timezone.now(),
            input_parameters={
                "herbs": ["黄芩"], "disease": "合成疾病", "statisticsVersion": "fixture-statistics-v1",
                "sourceCaseId": self.case.pk, "caseContentSha256": "a" * 64,
                "rawEvidenceVersion": "fixture-raw-v1",
            },
            result={
                "summary": {"candidateTargetCount": 2},
                "targets": [{"target": "TP53"}, {"target": "IL6"}],
                "network": {"nodes": [], "links": []},
                "limits": {"targetsTruncated": False},
                "charts": {"overlap": [{"name": "合成靶点", "value": 2}]},
            },
        )
        self.parent.source_releases.add(self.release)
        self.client.force_authenticate(self.owner)

    def linked_request(self, endpoint="pathway-enrichment", **extra):
        return self.client.post(
            reverse(endpoint), {"source_task_id": self.parent.pk, "consent": True, **extra}, format="json",
        )

    @patch("apps.core.tasks.run_external_analysis_task.apply_async")
    def test_linked_request_uses_saved_candidate_set_and_preserves_owner_case_and_source_versions(self, enqueue):
        response = self.linked_request(owner_id=self.other.pk, medical_case=999999)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["parent_task"], self.parent.pk)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(task.parent_task, self.parent)
        self.assertEqual(task.owner, self.owner)
        self.assertEqual(task.created_by, self.owner)
        self.assertEqual(task.medical_case, self.case)
        self.assertEqual(task.dataset, self.dataset)
        self.assertEqual(task.input_parameters["rawTargets"], ["TP53", "IL6"])
        self.assertEqual(task.input_parameters["sourceTaskId"], self.parent.pk)
        snapshot = task.input_parameters["parentProvenance"]
        self.assertEqual(snapshot["ownerId"], self.owner.pk)
        self.assertEqual(snapshot["inputParameters"]["caseContentSha256"], "a" * 64)
        self.assertEqual(snapshot["inputParameters"]["statisticsVersion"], "fixture-statistics-v1")
        self.assertEqual(snapshot["sourceReleases"], [{
            "id": self.release.pk, "sourceId": self.release.source_id, "sourceSlug": "parent-fixture",
            "version": "fixture-v1", "checksumSha256": "f" * 64,
        }])
        self.assertEqual(snapshot["medicalCaseId"], self.case.pk)
        self.assertEqual(snapshot["datasetId"], self.dataset.pk)
        self.assertEqual(len(snapshot["resultSha256"]), 64)
        self.assertEqual(list(task.source_releases.all()), [self.release])
        enqueue.assert_called_once_with(args=[task.pk])
        with self.assertRaises(ProtectedError):
            self.parent.delete()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(reverse("analysis-task-detail", args=[task.pk])).status_code, 404)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(reverse("analysis-task-detail", args=[task.pk])).status_code, 200)

    @patch("apps.core.tasks.run_external_analysis_task.apply_async")
    def test_string_accepts_equal_target_set_but_uses_server_order_and_unique_labels(self, enqueue):
        self.parent.result["targets"].append({"target": " TP53 "})
        self.parent.result["summary"]["candidateTargetCount"] = 3
        self.parent.save(update_fields=["result"])

        response = self.linked_request("string-network", targets=["IL6", "TP53", "TP53"], required_score=850)

        self.assertEqual(response.status_code, 202)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(task.input_parameters["rawTargets"], ["TP53", "IL6"])
        self.assertEqual(task.input_parameters["requiredScore"], 850)
        self.assertEqual(task.input_parameters["parentProvenance"]["candidateCount"], 3)
        self.assertEqual(task.input_parameters["parentProvenance"]["uniqueTargetCount"], 2)
        self.assertEqual(task.parent_task_id, self.parent.pk)
        enqueue.assert_called_once()

    @patch("apps.core.tasks.run_external_analysis_task.apply_async")
    def test_cross_owner_and_unknown_parent_are_hidden_even_from_administrator_creation(self, enqueue):
        count = AnalysisTask.objects.count()
        for user in (self.other, self.admin):
            self.client.force_authenticate(user)
            with self.subTest(user=user.username):
                self.assertEqual(self.linked_request().status_code, 404)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.linked_request(source_task_id=999999).status_code, 404)
        self.assertEqual(AnalysisTask.objects.count(), count)
        enqueue.assert_not_called()

    @patch("apps.core.tasks.run_external_analysis_task.apply_async")
    def test_only_successful_complete_local_network_parents_can_be_linked(self, enqueue):
        original_result = deepcopy(self.parent.result)
        original_parameters = deepcopy(self.parent.input_parameters)
        invalid_variants = [
            {"status": AnalysisTask.Status.FAILED},
            {"status": AnalysisTask.Status.QUEUED},
            {"task_type": AnalysisTask.TaskType.PROTEOMICS},
            {"input_parameters": {**original_parameters, "analysisKind": "string_ppi"}},
            {"input_parameters": {"disease": "合成疾病"}},
            {"result": {**original_result, "limits": {"targetsTruncated": True}}},
            {"result": {**original_result, "summary": {"candidateTargetCount": 3}}},
            {"result": {**original_result, "targets": [{"target": "TP53"}, {"target": ""}]}},
        ]
        for overrides in invalid_variants:
            with self.subTest(overrides=overrides):
                AnalysisTask.objects.filter(pk=self.parent.pk).update(
                    status=AnalysisTask.Status.SUCCEEDED, task_type=AnalysisTask.TaskType.NETWORK,
                    input_parameters=original_parameters, result=original_result,
                )
                AnalysisTask.objects.filter(pk=self.parent.pk).update(**overrides)
                count = AnalysisTask.objects.count()
                self.assertEqual(self.linked_request().status_code, 400)
                self.assertEqual(AnalysisTask.objects.count(), count)
        enqueue.assert_not_called()

    @patch("apps.core.tasks.run_external_analysis_task.apply_async")
    def test_changed_targets_partial_sets_and_missing_explicit_consent_are_rejected(self, enqueue):
        count = AnalysisTask.objects.count()
        for values in (
            {"targets": ["TP53", "PRIVATE_OTHER_TARGET"]},
            {"targets": ["TP53", "TP53"]},
            {"consent": False},
        ):
            with self.subTest(values=values):
                self.assertEqual(self.linked_request(**values).status_code, 400)
        self.assertEqual(self.client.post(reverse("pathway-enrichment"), {"consent": True}, format="json").status_code, 400)
        self.assertEqual(AnalysisTask.objects.count(), count)
        enqueue.assert_not_called()

    @patch("apps.core.tasks.run_external_analysis_task.apply_async")
    def test_provider_caps_do_not_silently_truncate_a_parent_candidate_set(self, enqueue):
        count = AnalysisTask.objects.count()
        for endpoint, row_count in (("string-network", 201), ("pathway-enrichment", 501)):
            with self.subTest(endpoint=endpoint):
                self.parent.result["targets"] = [{"target": f"SYN{index}"} for index in range(row_count)]
                self.parent.result["summary"]["candidateTargetCount"] = row_count
                self.parent.save(update_fields=["result"])
                self.assertEqual(self.linked_request(endpoint).status_code, 400)
        self.assertEqual(AnalysisTask.objects.count(), count)
        enqueue.assert_not_called()

    @patch("apps.core.tasks.run_external_analysis_task.apply_async")
    def test_parent_with_inconsistent_private_resource_ownership_is_rejected(self, enqueue):
        other_case = MedicalCase.objects.create(owner=self.other, title="其他私有医案", deidentified_text="合成文字")
        self.parent.medical_case = other_case
        self.parent.save(update_fields=["medical_case"])

        self.assertEqual(self.linked_request().status_code, 400)
        enqueue.assert_not_called()

    @patch("apps.core.tasks.run_external_analysis_task.apply_async", side_effect=RuntimeError("synthetic queue down"))
    def test_queue_failure_keeps_a_failed_private_child_with_frozen_provenance(self, enqueue):
        response = self.linked_request()

        self.assertEqual(response.status_code, 503)
        task = AnalysisTask.objects.get(parent_task=self.parent)
        self.assertEqual(task.status, AnalysisTask.Status.FAILED)
        self.assertEqual(task.owner, self.owner)
        self.assertEqual(task.medical_case, self.case)
        self.assertEqual(task.input_parameters["rawTargets"], ["TP53", "IL6"])
        self.assertIsNotNone(task.finished_at)
        enqueue.assert_called_once_with(args=[task.pk])

    @patch("apps.core.services.external_analysis._run_reactome")
    @patch("apps.core.tasks.run_external_analysis_task.apply_async")
    def test_worker_uses_frozen_targets_and_provenance_after_parent_or_source_metadata_change(self, enqueue, run_reactome):
        response = self.linked_request()
        task = AnalysisTask.objects.get(pk=response.data["id"])
        snapshot = deepcopy(task.input_parameters["parentProvenance"])
        self.parent.result["targets"] = [{"target": "CHANGED"}]
        self.parent.input_parameters["disease"] = "修改后的查询"
        self.parent.save(update_fields=["result", "input_parameters"])
        self.release.checksum_sha256 = "0" * 64
        self.release.save(update_fields=["checksum_sha256"])
        run_reactome.return_value = ({"analysisKind": "reactome_enrichment", "pathways": []}, None)

        outcome = run_external_analysis_task.run(task.pk)
        task.refresh_from_db()

        self.assertEqual(outcome["status"], AnalysisTask.Status.SUCCEEDED)
        run_reactome.assert_called_once_with(["TP53", "IL6"])
        self.assertEqual(task.result["inputProvenance"], {"sourceTaskId": self.parent.pk, "parentProvenance": snapshot})
        self.assertEqual(task.input_parameters["parentProvenance"], snapshot)
        self.assertEqual(snapshot["sourceReleases"][0]["checksumSha256"], "f" * 64)

    @patch("apps.core.services.external_analysis._run_reactome")
    @patch("apps.core.tasks.run_external_analysis_task.apply_async")
    def test_worker_rejects_altered_linked_input_before_any_provider_call(self, enqueue, run_reactome):
        response = self.linked_request()
        task = AnalysisTask.objects.get(pk=response.data["id"])
        task.input_parameters["rawTargets"] = ["PRIVATE_OTHER_TARGET", "IL6"]
        task.save(update_fields=["input_parameters"])

        outcome = run_external_analysis_task.run(task.pk)
        task.refresh_from_db()

        self.assertEqual(outcome["status"], AnalysisTask.Status.FAILED)
        self.assertIn("溯源信息不一致", task.error_summary)
        run_reactome.assert_not_called()

    @patch("apps.core.tasks.run_external_analysis_task.apply_async")
    def test_standalone_request_keeps_null_parent_and_does_not_guess_history(self, enqueue):
        historical = AnalysisTask.objects.create(
            owner=self.owner, task_type=AnalysisTask.TaskType.NETWORK,
            input_parameters={"analysisKind": "reactome_enrichment", "rawTargets": ["TP53", "IL6"]},
        )
        response = self.client.post(
            reverse("pathway-enrichment"), {"targets": ["TP53", "IL6"], "consent": True}, format="json",
        )

        self.assertEqual(response.status_code, 202)
        self.assertIsNone(response.data["parent_task"])
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertNotIn("parentProvenance", task.input_parameters)
        historical.refresh_from_db()
        self.assertIsNone(historical.parent_task_id)

    def test_new_r_chart_is_bound_and_reused_but_legacy_job_is_not_backfilled_or_returned_as_bound(self):
        from apps.core.services.visualization import queue_visualization

        job, created = queue_visualization(parent_task=self.parent, user=self.owner, chart_key="overlap")
        self.assertTrue(created)
        self.assertEqual(job.parent_task_id, self.parent.pk)
        self.assertEqual(job.input_parameters["parentTaskId"], self.parent.pk)
        reused, created = queue_visualization(parent_task=self.parent, user=self.owner, chart_key="overlap")
        self.assertFalse(created)
        self.assertEqual(reused.pk, job.pk)
        job.parent_task = None
        job.save(update_fields=["parent_task"])

        existing, created = queue_visualization(parent_task=self.parent, user=self.owner, chart_key="overlap")
        self.assertTrue(created)
        self.assertNotEqual(existing.pk, job.pk)
        self.assertEqual(existing.parent_task_id, self.parent.pk)
        job.refresh_from_db()
        self.assertIsNone(job.parent_task_id)

    @patch("apps.core.services.visualization._request_r_visualization")
    def test_r_worker_rejects_parent_parameter_mismatch_before_rendering(self, render):
        from apps.core.services.visualization import execute_visualization_task, queue_visualization, VisualizationInputError

        job, _ = queue_visualization(parent_task=self.parent, user=self.owner, chart_key="overlap")
        job.input_parameters["parentTaskId"] = 999999
        job.save(update_fields=["input_parameters"])
        with self.assertRaisesRegex(VisualizationInputError, "来源关联不一致"):
            execute_visualization_task(job)
        render.assert_not_called()


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
