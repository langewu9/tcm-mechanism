from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease
from apps.core.services.visualization import build_chart_payload


class CatalogAnalysisTests(APITestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="catalog-owner")
        self.other = get_user_model().objects.create_user(username="catalog-other")
        self.admin = get_user_model().objects.create_superuser(username="catalog-admin", email="admin@example.test")
        self.source = DataSource.objects.create(slug="historical-fixture", name="Historical fixture", access_mode="manual")
        self.release = SourceRelease.objects.create(source=self.source, version="fixture-v1")
        def entity(kind, stable_id, label):
            return KnowledgeEntity.objects.create(entity_type=kind, stable_id=stable_id, label=label, source_release=self.release)
        self.herb = entity("herb", "fixture:herb", "测试药")
        self.compound = entity("compound", "fixture:compound", "同名成分")
        # Preserve punctuation and same-name identities rather than guessing a symbol.
        name = "2-hydroxy-6-oxo-7-methylocta-2,4-dienoate hydrolase"
        self.targets = [entity("gene", f"fixture:target:{i}", name) for i in range(2)]
        self.records = []
        for index, (subject, object_, relation) in enumerate([
            (self.herb, self.compound, "contains"),
            (self.compound, self.targets[0], "targets"),
            (self.compound, self.targets[1], "targets"),
            (self.compound, self.targets[0], "targets"),
        ]):
            self.records.append(EvidenceRelation.objects.create(
                source_release=self.release, source_record_id=f"sheet-row:{index + 2}",
                subject=subject, object=object_, relation_type=relation, evidence_type="historical_table"))
        self.query = {"queryType": "herb", "queries": ["测试药"]}
        self.client.force_authenticate(self.owner)

    def search(self, query=None):
        response = self.client.post(reverse("batch-herb-evidence"), query or self.query, format="json")
        self.assertEqual(response.status_code, 200)
        return response.data

    def save(self, snapshot=None, query=None):
        return self.client.post(reverse("catalog-evidence-analysis"),
                                {**(query or self.query), "expectedResultSha256": (snapshot or self.search())["resultSha256"]}, format="json")

    def test_real_snapshot_preserves_ids_provenance_and_distinguishes_edge_counts(self):
        snapshot = self.search()
        self.assertEqual(snapshot["resultSha256"], self.search()["resultSha256"])
        self.assertEqual({row["id"] for row in snapshot["results"][0]["relations"]}, {row.pk for row in self.records})
        response = self.save(snapshot)
        self.assertEqual(response.status_code, 201)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(task.owner, self.owner)
        self.assertEqual(task.created_by, self.owner)
        self.assertEqual(task.status, "succeeded")
        self.assertEqual(list(task.source_releases.all()), [self.release])
        result = task.result
        self.assertEqual(result["counts"], {"nodes": 4, "evidenceRecords": 4, "returnedEvidenceRecords": 4, "uniqueEdges": 3})
        nodes = {row["id"]: row for row in result["network"]["nodes"]}
        self.assertEqual(len([row for row in nodes.values() if row["label"] == self.targets[0].label]), 2)
        self.assertEqual({row["sourceRecordId"] for row in result["evidenceRecords"]}, {row.source_record_id for row in self.records})
        self.assertTrue(all(link["source"] in nodes and link["target"] in nodes for link in result["network"]["links"]))
        payload = build_chart_payload(task, "evidence_network")
        self.assertEqual(len(payload["data"]), 4)
        self.assertEqual(len(payload["edges"]), 3)
        self.assertEqual({row["label"] for row in payload["data"] if row["type"] == "target"}, {self.targets[0].label})

    def test_changed_catalogue_cannot_silently_replace_searched_data(self):
        snapshot = self.search()
        self.targets[0].label = "Changed catalogue label"
        self.targets[0].save(update_fields=["label"])
        response = self.save(snapshot)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["code"], "CATALOG_RESULTS_CHANGED")
        self.assertIn("重新检索", response.data["error"]["message"])
        self.assertFalse(AnalysisTask.objects.exists())

    def test_saved_r_input_stays_stable_when_catalogue_later_changes(self):
        response = self.save()
        task = AnalysisTask.objects.get(pk=response.data["id"])
        before = build_chart_payload(task, "evidence_network")
        self.targets[0].label = "Changed later"
        self.targets[0].save(update_fields=["label"])
        self.records[0].is_active = False
        self.records[0].save(update_fields=["is_active"])
        task.refresh_from_db()
        self.assertEqual(build_chart_payload(task, "evidence_network"), before)

    def test_disabled_source_and_empty_query_cannot_produce_fake_graphs(self):
        snapshot = self.search()
        self.source.enabled = False
        self.source.save(update_fields=["enabled"])
        self.assertEqual(self.save(snapshot).status_code, 409)
        self.assertEqual(self.save().status_code, 400)
        self.assertFalse(AnalysisTask.objects.exists())

    def test_compound_query_uses_same_existing_evidence_and_private_task_permissions(self):
        query = {"queryType": "compound", "queries": [self.compound.label]}
        response = self.save(self.search(query), query)
        self.assertEqual(response.status_code, 201)
        task_id = response.data["id"]
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(reverse("analysis-task-detail", args=[task_id])).status_code, 404)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(reverse("analysis-task-detail", args=[task_id])).status_code, 200)
        self.client.force_authenticate(None)
        self.assertIn(self.save({"resultSha256": "0" * 64}).status_code, [401, 403])

    def test_graph_limit_is_reported_and_source_records_remain_identifiable(self):
        with patch("apps.core.services.catalog_analysis.MAX_GRAPH_RECORDS", 2):
            response = self.save()
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertTrue(task.result["limits"]["graphTruncated"])
        self.assertEqual(task.result["counts"]["returnedEvidenceRecords"], 4)
        self.assertEqual(task.result["counts"]["evidenceRecords"], 2)

    @override_settings(R_VIZ_BASE_URL="http://127.0.0.1:8001", R_VIZ_API_TOKEN="synthetic-test-token")
    def test_saved_catalog_task_uses_existing_private_visualization_pipeline(self):
        response = self.save()
        with patch("apps.core.tasks.run_visualization_task.apply_async") as queued:
            rendered = self.client.post(reverse("analysis-task-visualizations", args=[response.data["id"]]), {"chartKey": "evidence_network"}, format="json")
        self.assertEqual(rendered.status_code, 202)
        queued.assert_called_once()
        self.assertEqual(rendered.data["parent_task"], response.data["id"])
        self.assertEqual(rendered.data["owner_id"], self.owner.pk)
