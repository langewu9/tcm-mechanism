"""Interactions between platform catalogue identities and frozen evidence."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceEntityMapping, SourceRelease
from apps.core.serializers.research import ResearchAssistantRequestSerializer
from apps.core.services.complete_evidence import _catalog_data, _disease_data, _network_data
from apps.core.services.disease_evidence import search_disease_evidence
from apps.core.services.herb_evidence import batch_herb_component_evidence
from apps.core.services.network_pharmacology import _complete_identity_inputs


class PlatformMergeCompatibilityTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="merge-compat-owner")
        self.source = DataSource.objects.create(slug="merge-workbook", name="Synthetic workbook",
            configuration={"connector": "local-workbooks-master"})
        self.release = SourceRelease.objects.create(source=self.source, version="merge-v1", published_at=timezone.now())
        self.herb = self.entity("herb", "Herb")
        self.compound = self.entity("compound", "Compound")
        self.target = self.entity("protein", "TARGET")
        self.disease = self.entity("disease", "Disease")

    def entity(self, kind, label):
        return KnowledgeEntity.objects.create(entity_type=kind, label=label,
            stable_id=f"merge:{kind}:{label}", source_release=self.release)

    def edge(self, subject, object_, kind, key, **kwargs):
        return EvidenceRelation.objects.create(subject=subject, object=object_, relation_type=kind,
            source_record_id=key, source_release=self.release, **kwargs)

    def task(self, **params):
        return AnalysisTask.objects.create(owner=self.owner, task_type="network", input_parameters=params)

    def seed_structure(self):
        first = self.edge(self.herb, self.compound, "contains", "structure:1")
        repeated = self.edge(self.herb, self.compound, "contains", "structure:2")
        target = self.edge(self.compound, self.target, "targets", "target:1")
        return first, repeated, target

    def test_complete_catalogue_retains_rows_collapsed_in_platform_preview(self):
        rows = self.seed_structure()
        preview = batch_herb_component_evidence(query_type="herb", queries=[self.herb.label])
        self.assertEqual(len(preview["results"][0]["relations"]), 2)
        _, tables = _catalog_data(self.task(queryType="herb", queries=[self.herb.label],
            expectedResultSha256=preview["resultSha256"]), 20)
        self.assertEqual({row["id"] for row in tables["evidenceRecords"]}, {row.pk for row in rows})

    def test_complete_network_retains_all_source_rows_and_identity_result(self):
        rows = list(self.seed_structure())
        rows.append(self.edge(self.disease, self.target, "disease_target", "disease:target"))
        result, tables = _network_data(self.task(herb=self.herb.label, disease=self.disease.label), 20)
        self.assertEqual({row["id"] for row in tables["evidenceRecords"]}, {row.pk for row in rows})
        self.assertFalse(result["rawLimits"]["structuralRowsCollapsed"])
        self.assertIn("targetIdentity", result)
        self.assertEqual(result["summary"]["strictIntersectionCount"], 1)

    def test_complete_disease_retains_original_structural_evidence(self):
        first = self.edge(self.disease, self.herb, "disease_herb", "disease:herb:1")
        second = self.edge(self.disease, self.herb, "disease_herb", "disease:herb:2")
        preview = search_disease_evidence(self.disease.label)
        self.assertEqual(preview["counts"]["relations"], 1)
        _, tables = _disease_data(self.task(query=self.disease.label, expectedResultSha256=preview["resultSha256"]), 20)
        self.assertEqual({row["id"] for row in tables["evidenceRecords"]}, {first.pk, second.pk})

    def test_compound_lookup_keeps_observed_names_and_literal_alias_boundaries(self):
        SourceEntityMapping.objects.create(source_release=self.release, source_entity_id="MOL000001",
            source_label="Observed_%", namespace="tcmsp.mol_id", entity_type="compound", entity=self.compound, status="mapped")
        for query in ("Observed_%", "mol000001"):
            result = batch_herb_component_evidence(query_type="compound", queries=[query])["results"][0]
            self.assertEqual([row["id"] for row in result["matches"]], [self.compound.pk])
            self.assertFalse(result["resolution"]["identityMerged"])
        self.entity("compound", "Glycyrrhizic acid")
        result = batch_herb_component_evidence(query_type="compound", queries=["Glycyrrhizic-acid"])["results"][0]
        self.assertEqual(result["matches"], [])

    def test_identity_projection_cannot_cross_join_legacy_source_rows(self):
        self.release.metadata = {"connector": "sqlite-herb-compound-target"}
        self.release.save(update_fields=["metadata"])
        self.edge(self.herb, self.compound, "contains", "herb:1", metadata={"sourceRowId": 1})
        self.edge(self.compound, self.target, "targets", "target:1", metadata={"sourceRowId": 1})
        other_target = self.entity("protein", "UNRELATED")
        self.edge(self.compound, other_target, "targets", "target:2", metadata={"sourceRowId": 2})
        self.edge(self.disease, other_target, "disease_target", "disease:2")
        with patch("apps.core.services.network_pharmacology.compare_target_identities", return_value={}) as compare:
            _complete_identity_inputs({self.herb.pk}, {self.disease.pk}, set())
        compare.assert_called_once_with({self.target.pk}, {other_target.pk})

    def test_case_retrieval_and_scientist_report_request_modes_both_remain_valid(self):
        cases = ResearchAssistantRequestSerializer(data={"question": "Retrieve cases", "entityIds": [],
            "caseIds": [12], "caseCategory": "pulmonary"})
        self.assertTrue(cases.is_valid(), cases.errors)
        report = ResearchAssistantRequestSerializer(data={"mode": "scientist_hypothesis", "question": "Research plan",
            "disease": self.disease.label, "formula": self.herb.label})
        self.assertTrue(report.is_valid(), report.errors)
