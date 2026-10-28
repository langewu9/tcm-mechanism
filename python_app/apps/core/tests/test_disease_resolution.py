"""Intersection query translations are not broad search or identity merges."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceEntityMapping, SourceRelease
from apps.core.services.disease_resolution import ENTITY_LIMIT, resolve_intersection_disease
from apps.core.services.network_pharmacology import build_network_pharmacology


class IntersectionDiseaseResolutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username="disease-resolution-owner")
        cls.source = DataSource.objects.create(slug="resolution-fixture", name="合成匹配测试")
        cls.release = SourceRelease.objects.create(source=cls.source, version="v1", published_at=timezone.now())
        cls.herb = cls.entity("herb", "herb:fixture", "黄芩")
        cls.compound = cls.entity("compound", "compound:fixture", "合成成分")
        cls.target = cls.entity("protein", "protein:shared", "TP53")
        cls.disease = cls.entity("disease", "disease:pf", "Pulmonary fibrosis")
        cls.ipf = cls.entity("disease", "disease:ipf", "Idiopathic pulmonary fibrosis")
        cls.ild = cls.entity("disease", "disease:ild", "Interstitial lung disease")
        for kind, subject, object_ in [
            ("contains", cls.herb, cls.compound), ("targets", cls.compound, cls.target),
            ("disease_target", cls.disease, cls.target),
        ]:
            cls.relation(kind, subject, object_)

    @classmethod
    def entity(cls, kind, stable_id, label, **kwargs):
        return KnowledgeEntity.objects.create(entity_type=kind, stable_id=stable_id, label=label,
            source_release=kwargs.pop("source_release", cls.release), **kwargs)

    @classmethod
    def relation(cls, kind, subject, object_):
        return EvidenceRelation.objects.create(source_release=cls.release,
            source_record_id=f"{kind}:{subject.pk}:{object_.pk}", subject=subject,
            object=object_, relation_type=kind, evidence_type="synthetic-test")

    def result(self, query="肺纤维化", **kwargs):
        return build_network_pharmacology(user=self.owner, herb_query="黄芩", disease_query=query,
            persist=kwargs.pop("persist", False), **kwargs)

    def test_chinese_query_resolves_only_equivalent_whole_term_not_subtypes(self):
        entities, resolution = resolve_intersection_disease(" 肺纤维化 ")
        self.assertEqual([entity.pk for entity in entities], [self.disease.pk])
        self.assertEqual(resolution["status"], "alias")
        self.assertEqual(resolution["resolvedTerms"], ["Pulmonary fibrosis"])
        self.assertFalse(resolution["entitiesTruncated"])
        self.assertEqual(resolution["candidates"], [])
        result = self.result()
        self.assertEqual(result["summary"]["unmatchedDiseases"], [])
        self.assertEqual(result["summary"]["matchedDiseases"], ["Pulmonary fibrosis"])
        self.assertEqual(result["summary"]["strictIntersectionCount"], 1)
        self.assertEqual(AnalysisTask.objects.count(), 0)

    def test_english_exact_case_insensitive_query_is_preserved(self):
        entities, resolution = resolve_intersection_disease("pulmonary FIBROSIS")
        self.assertEqual([entity.pk for entity in entities], [self.disease.pk])
        self.assertEqual(resolution["status"], "exact")
        self.assertEqual(self.result("Idiopathic pulmonary fibrosis")["summary"]["matchedDiseases"], [self.ipf.label])

    def test_partial_unknown_and_broad_disease_names_never_auto_union(self):
        for query in ["肺纤维", "未知疾病", "间质性肺"]:
            entities, resolution = resolve_intersection_disease(query)
            self.assertEqual(entities, [])
            self.assertEqual(resolution["status"], "needs_selection" if query == "间质性肺" else "unmatched")
            result = self.result(query)
            self.assertEqual(result["summary"]["unmatchedDiseases"], [query])
            self.assertEqual(result["summary"]["diseaseTargetCount"], 0)
            self.assertEqual(result["summary"]["strictIntersectionCount"], 0)

    def test_missing_generic_disease_does_not_fall_back_to_ipf_or_ild(self):
        self.disease.is_active = False
        self.disease.save(update_fields=["is_active"])
        entities, resolution = resolve_intersection_disease("肺纤维化")
        self.assertEqual(entities, [])
        self.assertEqual(resolution["status"], "needs_selection")
        self.assertEqual({item["label"] for item in resolution["candidates"]}, {self.ipf.label, self.ild.label})

    def test_existing_chinese_and_english_source_records_are_selected_without_merge(self):
        chinese = self.entity("disease", "disease:chinese", "肺纤维化")
        another_target = self.entity("protein", "protein:separate", "TP53")
        self.relation("disease_target", chinese, another_target)
        result = self.result()
        self.assertEqual(set(result["summary"]["matchedDiseases"]), {"肺纤维化", "Pulmonary fibrosis"})
        self.assertEqual(result["summary"]["diseaseTargetCount"], 2)
        self.assertEqual(result["summary"]["strictIntersectionCount"], 1, "Same target label is not a shared identity")
        self.assertTrue(KnowledgeEntity.objects.filter(pk=another_target.pk, canonical_id=another_target.canonical_id).exists())

    def test_matching_source_observation_respects_publication_and_mapped_status(self):
        self.disease.label = "规范疾病实体"
        self.disease.save(update_fields=["label"])
        mapping = SourceEntityMapping.objects.create(source_release=self.release,
            source_entity_id="observed:pf", source_label="Pulmonary fibrosis", entity_type="disease",
            namespace="fixture", entity=self.disease, status="mapped", metadata={})
        self.assertEqual([e.pk for e in resolve_intersection_disease("肺纤维化")[0]], [self.disease.pk])
        mapping.status = "ambiguous"
        mapping.save(update_fields=["status"])
        self.assertEqual(resolve_intersection_disease("肺纤维化")[0], [])

    def test_disabled_and_inactive_sources_do_not_resolve_or_appear_as_suggestions(self):
        self.source.enabled = False
        self.source.save(update_fields=["enabled"])
        entities, resolution = resolve_intersection_disease("肺纤维化")
        self.assertEqual(entities, [])
        self.assertEqual(resolution["candidates"], [])

    def test_unreviewed_entity_synonym_does_not_change_disease_identity(self):
        self.ipf.synonyms = ["Pulmonary fibrosis"]
        self.ipf.save(update_fields=["synonyms"])
        self.assertEqual([e.pk for e in resolve_intersection_disease("肺纤维化")[0]], [self.disease.pk])

    def test_matched_disease_without_evidence_is_distinct_from_unmatched(self):
        result = self.result("Idiopathic pulmonary fibrosis")
        self.assertEqual(result["summary"]["unmatchedDiseases"], [])
        self.assertEqual(result["summary"]["diseaseTargetCount"], 0)
        self.assertEqual(result["summary"]["diseaseResolution"]["status"], "exact")

    def test_entity_query_bounds_are_disclosed(self):
        KnowledgeEntity.objects.bulk_create([
            KnowledgeEntity(entity_type="disease", stable_id=f"disease:bulk-{i}",
                label="Pulmonary fibrosis", source_release=self.release)
            for i in range(ENTITY_LIMIT)
        ])
        entities, resolution = resolve_intersection_disease("肺纤维化")
        self.assertEqual(len(entities), ENTITY_LIMIT)
        self.assertTrue(resolution["entitiesTruncated"])

    def test_saved_task_snapshots_resolution_and_old_task_is_immutable(self):
        before = self.result(persist=True)
        task = AnalysisTask.objects.get(pk=before["taskId"])
        self.assertEqual(task.input_parameters["diseaseResolution"], before["summary"]["diseaseResolution"])
        snapshot = task.result
        self.disease.label = "后来变更的名称"
        self.disease.save(update_fields=["label"])
        self.result(persist=True)
        task.refresh_from_db()
        self.assertEqual(task.result, snapshot)

    def test_api_preserves_auth_and_rejects_control_characters(self):
        client = APIClient()
        url = reverse("network-pharmacology")
        self.assertEqual(client.post(url, {"herb": "黄芩", "disease": "肺纤维化"}, format="json").status_code, 401)
        client.force_authenticate(self.owner)
        response = client.post(url, {"herb": "黄芩", "disease": "肺纤维化"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["diseaseResolution"]["status"], "alias")
        self.assertEqual(client.post(url, {"herb": "黄芩", "disease": "肺\x01纤维化"}, format="json").status_code, 400)
