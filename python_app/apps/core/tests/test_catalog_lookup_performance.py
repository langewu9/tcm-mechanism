"""Graph lookup regressions: evidence semantics and bounded provenance reads."""

from io import StringIO
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.core.models import DataSource, EvidenceRelation, KnowledgeEntity, SourceEntityMapping, SourceRelease
from apps.core.services.catalog_identity import exact_entity_queryset
from apps.core.services.herb_evidence import batch_herb_component_evidence


class CatalogLookupPerformanceTests(TestCase):
    def setUp(self):
        self.source = DataSource.objects.create(slug="lookup-fixture", name="Synthetic lookup fixture",
            access_mode="manual", configuration={"connector": "local-workbooks-master"})
        self.release = SourceRelease.objects.create(source=self.source, version="fixture-v1", published_at=timezone.now())
        self.herb = self.entity("herb", "herb:a", "合成中药")

    def entity(self, kind, stable_id, label):
        return KnowledgeEntity.objects.create(entity_type=kind, stable_id=stable_id, label=label, source_release=self.release)

    def edge(self, subject, object, kind, record, **extra):
        return EvidenceRelation.objects.create(subject=subject, object=object, relation_type=kind,
            source_release=self.release, source_record_id=record, evidence_type="fixture", **extra)

    def search(self, query="合成中药", kind="herb"):
        return batch_herb_component_evidence(query_type=kind, queries=[query])["results"][0]

    def test_exact_alias_uses_published_enabled_observations_and_literal_names(self):
        canonical = self.entity("compound", "compound:a", "Canonical compound")
        SourceEntityMapping.objects.create(source_release=self.release, source_entity_id="c1", source_label="Alias_%",
            entity_type="compound", namespace="fixture", entity=canonical, status="mapped", metadata={})
        self.assertEqual(list(exact_entity_queryset("compound", "alias_%")), [canonical])
        self.assertFalse(exact_entity_queryset("compound", "Alias_XX").exists())
        self.assertFalse(exact_entity_queryset("herb", "Alias_%").exists())
        self.release.published_at = None
        self.release.save(update_fields=["published_at"])
        self.assertFalse(exact_entity_queryset("compound", "Alias_%").exists())
        self.source.enabled = False
        self.source.save(update_fields=["enabled"])
        self.assertFalse(exact_entity_queryset("compound", "Canonical compound").exists())

    def test_structure_collapses_per_release_and_type_but_target_evidence_stays(self):
        compound = self.entity("compound", "compound:a", "合成成分")
        target = self.entity("protein", "protein:a", "SYN_TARGET")
        ignored = self.edge(self.herb, compound, "contains", "inactive", is_active=False)
        first = self.edge(self.herb, compound, "contains", "structure:first")
        self.edge(self.herb, compound, "contains", "structure:repeat")
        alternative = self.edge(self.herb, compound, "has_compound", "structure:alternative")
        targets = [self.edge(compound, target, "targets", f"target:{i}") for i in range(2)]
        result = self.search()
        self.assertEqual([r["relationId"] for r in result["relations"]], [first.pk, alternative.pk, *(r.pk for r in targets)])
        self.assertEqual(len(result["compounds"]), 1)
        self.assertEqual(len(result["targets"]), 1)
        self.assertFalse(result["truncated"])
        self.assertTrue(EvidenceRelation.objects.filter(pk=ignored.pk).exists())
        self.assertEqual(EvidenceRelation.objects.count(), 6)
        reverse_result = self.search("合成成分", "compound")
        self.assertEqual(result["relations"], reverse_result["relations"])

    def test_legacy_sources_without_connector_keep_all_evidence_rows(self):
        self.source.configuration = {}
        self.source.save(update_fields=["configuration"])
        compound = self.entity("compound", "compound:a", "合成成分")
        for i in range(2):
            self.edge(self.herb, compound, "contains", f"legacy:{i}")
        self.assertEqual(len(self.search()["relations"]), 2)

    def test_provenance_query_count_does_not_grow_with_graph_size(self):
        for i in range(70):
            compound = self.entity("compound", f"compound:{i}", f"合成成分{i}")
            target = self.entity("protein", f"protein:{i}", f"SYN_TARGET_{i}")
            self.edge(self.herb, compound, "contains", f"hc:{i}")
            self.edge(compound, target, "targets", f"ct:{i}")
        with CaptureQueriesContext(connection) as queries:
            result = self.search()
        self.assertEqual((len(result["compounds"]), len(result["targets"])), (70, 70))
        self.assertTrue(all(item["sourceSlug"] == self.source.slug for item in result["targets"]))
        # One constant lookup adds the published data-quality/version notice.
        # Provenance must still be fetched in batches, never once per edge.
        self.assertLessEqual(len(queries), 12)

    def test_target_limit_remains_explicit_and_preserves_row_order(self):
        compound = self.entity("compound", "compound:a", "合成成分")
        target = self.entity("protein", "protein:a", "SYN_TARGET")
        self.edge(self.herb, compound, "contains", "hc")
        EvidenceRelation.objects.bulk_create([
            EvidenceRelation(subject=compound, object=target, relation_type="targets", source_release=self.release,
                source_record_id=f"target:{i}", evidence_type="fixture") for i in range(1201)
        ])
        result = self.search()
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["relations"]), 1201)
        self.assertEqual(result["relations"][-1]["sourceRecordId"], "target:1199")

    def test_provenance_hydration_has_explicit_bounded_ids(self):
        from apps.core.services.herb_evidence import _visible_relations
        compound = self.entity("compound", "compound:bounded", "合成成分")
        first = self.edge(self.herb, compound, "contains", "bounded:first")
        self.edge(self.herb, compound, "has_compound", "bounded:second")
        with CaptureQueriesContext(connection) as captured:
            rows, truncated = _visible_relations(
                relation_types={"contains", "has_compound"}, subject_ids=[self.herb.pk], complete=True, limit=1,
            )
        self.assertEqual([row.pk for row in rows], [first.pk])
        self.assertTrue(truncated)
        # The final select_related read must not fold the ID limit into a
        # semi-join that hydrates the entire table before filtering.
        hydration = captured[-1]["sql"]
        self.assertIn('"core_evidencerelation"."id" IN (', hydration)
        self.assertNotIn('"core_evidencerelation"."id" IN (SELECT', hydration)

    def test_planner_maintenance_preserves_records_and_restores_connection_options(self):
        if connection.vendor != "sqlite":
            self.skipTest("SQLite-specific planner maintenance")
        models = [DataSource, SourceRelease, KnowledgeEntity, SourceEntityMapping, EvidenceRelation]
        before = [model.objects.count() for model in models]
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA analysis_limit")
            original = cursor.fetchone()[0]
        call_command("optimize_catalog_lookup", stdout=StringIO())
        self.assertEqual([model.objects.count() for model in models], before)
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA analysis_limit")
            self.assertEqual(cursor.fetchone()[0], original)
