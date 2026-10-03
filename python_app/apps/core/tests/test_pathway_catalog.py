from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease


class ReactomePathwayCatalogTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="pathway-reader", password="test-password-123")
        cls.source, _ = DataSource.objects.update_or_create(
            slug="reactome", defaults={"name": "Reactome", "access_mode": "download", "enabled": True},
        )
        cls.release = SourceRelease.objects.create(source=cls.source, version="fixture-real-v103+abc", checksum_sha256="a" * 64)
        cls.other_source = DataSource.objects.create(slug="other-pathway-source", name="另一来源", access_mode="manual")
        cls.other_release = SourceRelease.objects.create(source=cls.other_source, version="other-v2")
        cls.first = cls.entity("R-HSA-100", "Alpha Interleukin")
        cls.second = cls.entity("R-HSA-200", "Beta Signaling")

    @classmethod
    def entity(cls, stable_id, label, **kwargs):
        return KnowledgeEntity.objects.create(
            entity_type=kwargs.pop("entity_type", "pathway"), stable_id=stable_id, label=label,
            organism=kwargs.pop("organism", "Homo sapiens"),
            source_release=kwargs.pop("source_release", cls.release), **kwargs,
        )

    def get(self, query=None):
        return self.client.get(reverse("reactome-pathway-catalog"), {} if query is None else {"query": query})

    def authenticate(self):
        self.client.force_authenticate(self.user)

    def test_authenticated_shared_catalogue_returns_real_versions_and_no_private_enrichment_data(self):
        self.assertEqual(self.get().status_code, 401)
        other_user = get_user_model().objects.create_user(username="private-analysis-owner")
        AnalysisTask.objects.create(owner=other_user, task_type="network", result={"privateEnrichment": "secret-result"})
        self.authenticate()
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["catalogTotal"], 2)
        self.assertEqual(response.data["sources"][0]["sourceVersion"], "fixture-real-v103+abc")
        self.assertEqual(response.data["sources"][0]["checksumSha256"], "a" * 64)
        self.assertTrue(all(row["enrichmentRecords"] is None for row in response.data["items"]))
        self.assertNotIn("secret-result", str(response.data))
        self.assertEqual(response.data["items"][0]["sourceUrl"], "https://reactome.org/content/detail/R-HSA-100")

    def test_name_and_stable_id_search_trim_case_and_reject_excessive_input(self):
        self.authenticate()
        self.assertEqual([row["stableId"] for row in self.get("  interLEUKIN  ").data["items"]], ["R-HSA-100"])
        self.assertEqual([row["stableId"] for row in self.get("r-hsa-200").data["items"]], ["R-HSA-200"])
        self.assertEqual(self.get("no matching pathway").data["items"], [])
        self.assertEqual(self.get(" ").data["matchedTotal"], 2)
        invalid = self.get("x" * 161)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.data["error"]["code"], "VALIDATION_ERROR")

    def test_only_active_versioned_reactome_human_pathways_are_included(self):
        self.entity("R-HSA-301", "Inactive", is_active=False)
        self.entity("R-MMU-302", "Mouse", organism="Mus musculus")
        self.entity("R-HSA-303", "Wrong source", source_release=self.other_release)
        self.entity("R-HSA-304", "No source", source_release=None)
        self.entity("R-HSA-305", "Wrong type", entity_type="gene")
        self.entity("R-HSA-306/script", "Unsafe external ID")
        self.authenticate()
        self.assertEqual(self.get().data["catalogTotal"], 2)
        self.source.enabled = False
        self.source.save(update_fields=["enabled"])
        empty = self.get().data
        self.assertEqual(empty["catalogTotal"], 0)
        self.assertEqual(empty["items"], [])
        self.assertEqual(empty["sources"], [])

    def test_maximum_100_rows_are_name_ordered_and_truncation_is_explicit(self):
        KnowledgeEntity.objects.bulk_create([
            KnowledgeEntity(entity_type="pathway", stable_id=f"R-HSA-{index + 1000}", label=f"Zeta {index:03d}", organism="Homo sapiens", source_release=self.release)
            for index in range(103)
        ])
        self.authenticate()
        data = self.get().data
        self.assertEqual(data["catalogTotal"], 105)
        self.assertEqual(data["matchedTotal"], 105)
        self.assertEqual(len(data["items"]), 100)
        self.assertTrue(data["truncated"])
        self.assertEqual(data["items"][0]["name"], "Alpha Interleukin")
        self.assertEqual(data["items"][-1]["name"], "Zeta 097")

    def test_annotations_count_distinct_enabled_active_gene_protein_targets_with_provenance(self):
        gene = self.entity("gene:1", "GENE1", entity_type="gene")
        protein = self.entity("protein:1", "PROTEIN1", entity_type="protein")
        compound = self.entity("compound:1", "Compound", entity_type="compound")
        inactive = self.entity("gene:inactive", "Inactive", entity_type="gene", is_active=False)
        for index, subject in enumerate([gene, gene, protein, compound, inactive]):
            EvidenceRelation.objects.create(subject=subject, object=self.first, relation_type="gene_pathway", source_release=self.other_release, source_record_id=str(index), evidence_type="fixture")
        EvidenceRelation.objects.create(subject=gene, object=self.first, relation_type="unrelated", source_release=self.release, source_record_id="ignored", evidence_type="fixture")
        self.authenticate()
        row = self.get("Interleukin").data["items"][0]
        self.assertEqual(row["targetAnnotations"], 2)
        self.assertEqual(row["annotationSources"], [{"sourceSlug": "other-pathway-source", "sourceVersion": "other-v2"}])
        self.other_source.enabled = False
        self.other_source.save(update_fields=["enabled"])
        self.assertEqual(self.get("Interleukin").data["items"][0]["targetAnnotations"], 0)

    def test_disabled_target_source_and_inactive_evidence_are_excluded(self):
        gene = self.entity("gene:disabled", "Disabled source target", entity_type="gene", source_release=self.other_release)
        active_gene = self.entity("gene:active", "Active", entity_type="gene")
        for index, subject in enumerate([gene, active_gene]):
            EvidenceRelation.objects.create(subject=subject, object=self.first, relation_type="gene_pathway", source_release=self.release, source_record_id=str(index), evidence_type="fixture", is_active=index == 0)
        self.other_source.enabled = False
        self.other_source.save(update_fields=["enabled"])
        self.authenticate()
        row = self.get("Interleukin").data["items"][0]
        self.assertEqual(row["targetAnnotations"], 0)
        self.assertEqual(row["annotationSources"], [])
