from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease
from apps.core.services.visualization import build_chart_payload, VisualizationInputError


class CatalogVisualizationTests(APITestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="catalog-r-owner")
        self.other = get_user_model().objects.create_user(username="catalog-r-other")
        self.source = DataSource.objects.create(slug="catalog-r-fixture", name="Synthetic unit test", access_mode="manual", enabled=True)
        self.release = SourceRelease.objects.create(source=self.source, version="SYNTHETIC-v1")
        self.herb = self.entity("herb", "herb:a", "合成中药")
        self.compound = self.entity("compound", "compound:a", "合成成分")
        self.targets = [self.entity("gene", "gene:a", "SYN_GENE"), self.entity("protein", "protein:b", "SYN_GENE")]
        self.relate(self.herb, self.compound, "contains", "contains-1")
        for index, target in enumerate(self.targets): self.relate(self.compound, target, "targets", f"target-{index}")
        self.client.force_authenticate(self.owner)

    def entity(self, kind, stable_id, label):
        return KnowledgeEntity.objects.create(entity_type=kind, stable_id=stable_id, label=label, source_release=self.release)

    def relate(self, subject, object, kind, record):
        return EvidenceRelation.objects.create(subject=subject, object=object, relation_type=kind, evidence_type="SYNTHETIC", source_release=self.release, source_record_id=record)

    def search(self, query="合成中药"):
        response = self.client.post(reverse("batch-herb-evidence"), {"queryType": "herb", "queries": [query]}, format="json")
        self.assertEqual(response.status_code, 200)
        return response.data

    def snapshot(self, response, **extra):
        return self.client.post(reverse("catalog-visualization-snapshot"), {"queryType": "herb", "queries": [response["results"][0]["query"]], "expectedSha256": response["evidenceSha256"], **extra}, format="json")

    def test_primary_key_graph_retains_same_name_targets_and_provenance(self):
        response = self.snapshot(self.search())
        self.assertEqual(response.status_code, 200)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        nodes = task.result["network"]["nodes"]
        self.assertEqual(len([node for node in nodes if node["label"] == "SYN_GENE"]), 2)
        self.assertEqual(len({node["id"] for node in nodes}), 4)
        self.assertEqual(list(task.source_releases.all()), [self.release])
        payload = build_chart_payload(task, "evidence_network")
        self.assertEqual(len(payload["data"]), 4)
        self.assertEqual(len(payload["edges"]), 3)
        self.assertTrue(all(edge["evidence"][0]["sourceVersion"] == "SYNTHETIC-v1" for edge in payload["edges"]))
        summary = build_chart_payload(task, "catalog_summary")
        self.assertEqual(next(row["value"] for row in summary["data"] if row["label"] == "靶点实体"), 2)
        degree = build_chart_payload(task, "catalog_degree")
        self.assertEqual(max(row["value"] for row in degree["data"]), 3)

    def test_changed_directory_rejected_old_snapshot_remains_immutable(self):
        data = self.search()
        task_id = self.snapshot(data).data["id"]
        self.targets[0].label = "RENAMED_SYNTHETIC_GENE"
        self.targets[0].save(update_fields=["label"])
        stale = self.snapshot(data)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(AnalysisTask.objects.count(), 1)
        self.assertIn("SYN_GENE", str(AnalysisTask.objects.get(pk=task_id).result))
        latest = self.snapshot(self.search())
        self.assertNotEqual(latest.data["id"], task_id)

    def test_repeated_click_reuses_owner_snapshot_and_cannot_inject_edges(self):
        data = self.search()
        first = self.snapshot(data)
        second = self.snapshot(data, network={"nodes": [{"id": "FAKE_NODE"}], "links": [{"source": "FAKE"}]})
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertNotIn("FAKE_NODE", str(second.data))
        self.client.force_authenticate(self.other)
        another = self.snapshot(data)
        self.assertNotEqual(first.data["id"], another.data["id"])
        self.assertEqual(self.client.get(f'/api/v1/research/analysis-tasks/{first.data["id"]}/').status_code, 404)

    def test_no_evidence_keeps_zero_statistics_but_cannot_draw_fake_network(self):
        response = self.snapshot(self.search("无目录匹配"))
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertTrue(all(row["value"] == 0 for row in build_chart_payload(task, "catalog_summary")["data"]))
        with self.assertRaises(VisualizationInputError): build_chart_payload(task, "evidence_network")
        with self.assertRaises(VisualizationInputError): build_chart_payload(task, "catalog_degree")

    def test_disabled_source_is_not_exposed_and_unauthenticated_creation_fails(self):
        self.source.enabled = False
        self.source.save(update_fields=["enabled"])
        self.assertEqual(self.search()["results"][0]["matches"], [])
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(reverse("catalog-visualization-snapshot"), {}, format="json").status_code, 401)

    def test_disease_and_entity_queries_use_same_fingerprint_and_source(self):
        disease = self.entity("disease", "disease:a", "合成疾病")
        self.relate(disease, self.targets[0], "disease_target", "disease-1")
        data = self.client.get(reverse("disease-evidence-search"), {"query": "合成疾病"}).data
        response = self.client.post(reverse("catalog-visualization-snapshot"), {"queryType": "disease", "queries": ["合成疾病"], "expectedSha256": data["evidenceSha256"]}, format="json")
        self.assertEqual(response.status_code, 200)
        data = self.client.get(reverse("entity-neighborhood", kwargs={"entity_id": self.compound.pk})).data
        response = self.client.post(reverse("catalog-visualization-snapshot"), {"queryType": "entity", "entityId": self.compound.pk, "expectedSha256": data["evidenceSha256"]}, format="json")
        self.assertEqual(response.status_code, 200)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(task.source_releases.get(), self.release)
        self.assertIn("contains-1", str(task.result["network"]))

    def test_pathway_coverage_is_not_enrichment_and_retains_annotation_sources(self):
        source, _ = DataSource.objects.update_or_create(slug="reactome", defaults={"name": "Reactome", "access_mode": "manual", "enabled": True})
        release = SourceRelease.objects.create(source=source, version="SYNTHETIC-pathway-v1")
        pathway = KnowledgeEntity.objects.create(entity_type="pathway", stable_id="R-HSA-12345", label="Synthetic pathway", organism="Homo sapiens", source_release=release)
        self.relate(self.targets[0], pathway, "participates_in", "pathway-annotation")
        data = self.client.get(reverse("reactome-pathway-catalog"), {"query": "Synthetic"}).data
        response = self.client.post(reverse("catalog-visualization-snapshot"), {"queryType": "pathway", "queries": ["Synthetic"], "expectedSha256": data["evidenceSha256"]}, format="json")
        self.assertEqual(response.status_code, 200)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(set(task.source_releases.all()), {self.release, release})
        payload = build_chart_payload(task, "catalog_degree")
        self.assertEqual(payload["data"], [{"label": "Synthetic pathway", "value": 1}])
        self.assertIn("非统计富集", payload["yLabel"])

    def test_name_comparison_snapshot_does_not_invent_biological_network(self):
        values = {"detected": "甘草酸、Liquiritin", "reference": "Glycyrrhizic acid、未知合成名称"}
        data = self.client.post(reverse("component-compare"), values, format="json").data
        rebuilt = {"detected": "\n".join(row["input"] for row in data["detected"]), "reference": "\n".join(row["input"] for row in data["reference"])}
        response = self.client.post(reverse("catalog-visualization-snapshot"), {"queryType": "comparison", **rebuilt, "expectedSha256": data["evidenceSha256"]}, format="json")
        self.assertEqual(response.status_code, 200)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(task.result["network"], {"nodes": [], "links": []})
        payload = build_chart_payload(task, "catalog_summary")
        self.assertIn("名称对照", payload["title"])
        self.assertIn(data["aliasSourceCommit"], payload["subtitle"])
        with self.assertRaises(VisualizationInputError): build_chart_payload(task, "evidence_network")
