"""Exact multilingual compound retrieval must not become identity merging."""
from django.test import TestCase
from django.utils import timezone

from apps.core.models import DataSource, EvidenceRelation, KnowledgeEntity, SourceEntityMapping, SourceRelease
from apps.core.services.catalog_identity import exact_entity_names, exact_entity_queryset
from apps.core.services.herb_evidence import batch_herb_component_evidence


class CompoundCatalogNameTests(TestCase):
    def setUp(self):
        self.source = DataSource.objects.create(slug="compound-name-fixture", name="Synthetic synonym fixture", enabled=True)
        self.release = SourceRelease.objects.create(source=self.source, version="fixture-v1", published_at=timezone.now())

    def entity(self, key, label, kind="compound"):
        return KnowledgeEntity.objects.create(entity_type=kind, stable_id=key, label=label, source_release=self.release)

    def test_chinese_english_and_latin_find_same_source_scoped_records(self):
        first = self.entity("compound:one", "Glycyrrhizic acid")
        second = self.entity("compound:two", "glycyrrhizin")
        third = self.entity("compound:three", "glycyrrhizinic acid")
        original = list(KnowledgeEntity.objects.order_by("pk").values("pk", "label", "stable_id"))
        for query in ["甘草酸", "Glycyrrhizic acid", "GLYCYRRHIZIN", "Acidum glycyrrhizicum"]:
            self.assertEqual(set(exact_entity_queryset("compound", query).values_list("pk", flat=True)), {first.pk, second.pk, third.pk})
        self.assertEqual(list(KnowledgeEntity.objects.order_by("pk").values("pk", "label", "stable_id")), original)

    def test_exact_tcmsp_molecule_identifier_does_not_merge_same_name_records(self):
        first = self.entity('tcmsp:mol:1', 'Same compound name')
        second = self.entity('tcmsp:mol:2', 'Same compound name')
        for identifier, entity in [('MOL000001', first), ('MOL000002', second)]:
            SourceEntityMapping.objects.create(source_release=self.release, source_entity_id=identifier,
                source_label=entity.label, entity_type='compound', namespace='tcmsp.mol_id', entity=entity, status='mapped')
        self.assertEqual(list(exact_entity_queryset('compound', 'mol000001')), [first])
        self.assertFalse(exact_entity_queryset('compound', 'MOL00000').exists())
        first.is_active=False;first.save()
        self.assertFalse(exact_entity_queryset('compound', 'MOL000001').exists())

    def test_salts_aglycone_and_partial_names_are_not_matches(self):
        right = self.entity("compound:right", "Glycyrrhizic acid")
        for i, label in enumerate(["Glycyrrhizic acid ammonium salt", "Dipotassium glycyrrhizinate", "Glycyrrhetinic acid", "Araboglycyrrhizin"]):
            self.entity(f"compound:wrong:{i}", label)
        self.assertEqual(list(exact_entity_queryset("compound", "甘草酸")), [right])
        self.assertFalse(exact_entity_queryset("compound", "Glycyrrhiz").exists())

    def test_alias_observations_still_require_published_enabled_sources(self):
        canonical = self.entity("compound:cid", "Canonical fixture")
        SourceEntityMapping.objects.create(source_release=self.release, source_entity_id="c1", source_label="Glycyrrhizin",
            entity_type="compound", namespace="fixture", entity=canonical, status="mapped", metadata={})
        self.assertEqual(list(exact_entity_queryset("compound", "甘草酸")), [canonical])
        self.release.published_at = None
        self.release.save(update_fields=["published_at"])
        self.assertFalse(exact_entity_queryset("compound", "甘草酸").exists())
        self.release.published_at = timezone.now()
        self.release.save(update_fields=["published_at"])
        self.source.enabled = False
        self.source.save(update_fields=["enabled"])
        self.assertFalse(exact_entity_queryset("compound", "甘草酸").exists())

    def test_family_names_are_not_expanded_into_distinct_compounds(self):
        self.entity("compound:rg1", "Ginsenoside Rg1")
        self.entity("compound:rg2", "Ginsenoside Rg2")
        self.assertEqual(exact_entity_names("compound", "人参皂苷"), ["人参皂苷"])
        self.assertFalse(exact_entity_queryset("compound", "人参皂苷").exists())
        self.assertFalse(exact_entity_queryset("herb", "甘草酸").exists())

    def test_batch_alias_query_returns_local_relations_and_explains_names(self):
        compound = self.entity("compound:a", "Glycyrrhizic acid")
        herb = self.entity("herb:a", "合成来源中药", "herb")
        target = self.entity("protein:a", "SYN_TARGET", "protein")
        for subject, object, kind in [(herb, compound, "contains"), (compound, target, "targets")]:
            EvidenceRelation.objects.create(subject=subject, object=object, relation_type=kind,
                source_release=self.release, source_record_id=kind, evidence_type="synthetic")
        result = batch_herb_component_evidence(query_type="compound", queries=["甘草酸"])["results"][0]
        self.assertEqual([row["id"] for row in result["matches"]], [compound.pk])
        self.assertEqual([row["id"] for row in result["herbs"]], [herb.pk])
        self.assertEqual([row["id"] for row in result["targets"]], [target.pk])
        self.assertIn("Glycyrrhizin", result["searchedNames"])
