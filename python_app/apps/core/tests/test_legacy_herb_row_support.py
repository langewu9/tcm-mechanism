"""Shared compounds must not fabricate legacy herb/target source rows."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.core.models import DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease
from apps.core.services.catalog_analysis import save_catalog_analysis
from apps.core.services.herb_evidence import batch_herb_component_evidence
from apps.core.services.network_pharmacology import build_network_pharmacology
from apps.core.services.herb_row_query import supported_target_queryset
from apps.core.services.herb_row_support import HerbRowSupport


class LegacyHerbRowSupportTests(TestCase):
    def setUp(self):
        source = DataSource.objects.create(slug="row-support", name="Synthetic legacy triples")
        self.release = SourceRelease.objects.create(source=source, version="rows-v1", metadata={"connector": "sqlite-herb-compound-target"})
        self.user = get_user_model().objects.create_user(username="row-support-owner")
        self.a = self.entity("herb", "Herb A")
        self.b = self.entity("herb", "Herb B")
        self.compound = self.entity("compound", "Shared compound")
        self.t1 = self.entity("protein", "TARGET1")
        self.t2 = self.entity("protein", "TARGET2")
        self.disease = self.entity("disease", "Test disease")
        self.edge(self.a, self.compound, "contains", 2)
        self.edge(self.compound, self.t1, "targets", 2)
        self.edge(self.b, self.compound, "contains", 3)
        self.edge(self.compound, self.t2, "targets", 3)
        self.edge(self.disease, self.t1, "disease_target", 4)
        self.edge(self.disease, self.t2, "disease_target", 5)

    def entity(self, kind, label):
        return KnowledgeEntity.objects.create(entity_type=kind, stable_id=f"fixture:{kind}:{label}", label=label, source_release=self.release)

    def edge(self, subject, object_, kind, row, *, release=None, metadata=None):
        return EvidenceRelation.objects.create(subject=subject, object=object_, relation_type=kind,
            source_release=release or self.release, source_record_id=f"{row}:{subject.pk}:{object_.pk}",
            metadata={"sourceRowId": row} if metadata is None else metadata)

    def search(self, name="Herb A", query_type="herb"):
        return batch_herb_component_evidence(query_type=query_type, queries=[name])

    def network(self, herbs="Herb A"):
        return build_network_pharmacology(user=self.user, herb_query=herbs, disease_query="Test disease", persist=False)

    def test_herb_search_uses_only_matching_original_rows(self):
        result = self.search()["results"][0]
        self.assertEqual([row["label"] for row in result["targets"]], ["TARGET1"])
        self.assertEqual(len(result["relations"]), 2)

    def test_component_query_keeps_both_herbs_and_targets(self):
        result = self.search("Shared compound", "compound")["results"][0]
        self.assertEqual({row["label"] for row in result["herbs"]}, {"Herb A", "Herb B"})
        self.assertEqual({row["label"] for row in result["targets"]}, {"TARGET1", "TARGET2"})

    def test_saved_graph_uses_scoped_query_evidence(self):
        task = save_catalog_analysis(user=self.user, query_type="herb", queries=["Herb A"], expected_sha256=self.search()["resultSha256"])
        self.assertEqual(task.input_parameters["algorithmVersion"], "catalog-evidence-0.4")
        self.assertEqual(task.result["counts"]["evidenceRecords"], 2)
        self.assertNotIn("TARGET2", {node["label"] for node in task.result["network"]["nodes"]})

    def test_network_candidates_charts_and_raw_exports_share_the_same_scope(self):
        result = self.network()
        self.assertEqual(result["summary"]["herbTargetCount"], 1)
        self.assertEqual(result["summary"]["strictIntersectionCount"], 1)
        self.assertEqual([row["target"] for row in result["targets"]], ["TARGET1"])
        self.assertEqual(result["charts"]["components"], [{"name": "Shared compound", "targets": 1}])
        self.assertEqual([(row["herb"], row["target"]) for row in result["raw"]["herbLinks"]], [("Herb A", "TARGET1")])

    def test_multi_herb_results_keep_correct_per_target_herb_support(self):
        result = self.network("Herb A、Herb B")
        self.assertEqual({row["target"]: row["herbs"] for row in result["targets"]}, {"TARGET1": ["Herb A"], "TARGET2": ["Herb B"]})
        self.assertEqual(len(result["raw"]["herbLinks"]), 2)
        self.assertTrue(all(row["sourceRecordId"].split(":")[0] == row["herbSourceRecordId"].split(":")[0]
                            for row in result["raw"]["herbLinks"]))

    def test_equal_row_numbers_from_different_releases_do_not_join(self):
        other = SourceRelease.objects.create(source=self.release.source, version="other-v2", metadata=self.release.metadata)
        self.edge(self.compound, self.t2, "targets", 2, release=other)
        self.assertEqual([row["label"] for row in self.search()["results"][0]["targets"]], ["TARGET1"])

    def test_missing_legacy_row_id_does_not_become_a_global_annotation(self):
        self.edge(self.compound, self.t2, "targets", 8, metadata={})
        self.assertEqual([row["label"] for row in self.search()["results"][0]["targets"]], ["TARGET1"])

    def test_generic_graph_annotation_still_applies_to_a_shared_compound(self):
        generic = SourceRelease.objects.create(source=self.release.source, version="generic-v1")
        self.edge(self.compound, self.t2, "targets", 9, release=generic, metadata={})
        self.assertEqual({row["label"] for row in self.search()["results"][0]["targets"]}, {"TARGET1", "TARGET2"})
        self.assertEqual(len(self.network()["raw"]["herbLinks"]), 2)

    def test_same_row_number_from_another_source_cannot_support_this_herb(self):
        other = DataSource.objects.create(slug="other-row-source", name="Other synthetic source")
        release = SourceRelease.objects.create(source=other, version=self.release.version, metadata=self.release.metadata)
        self.edge(self.compound, self.t2, "targets", 2, release=release)
        self.assertEqual([row["label"] for row in self.search()["results"][0]["targets"]], ["TARGET1"])
        self.assertEqual([row["target"] for row in self.network()["targets"]], ["TARGET1"])

    def test_invalid_target_row_ids_are_not_coerced_to_valid_row_numbers(self):
        for value in (True, False, "2", 2.0, None, [], {}):
            with self.subTest(value=value):
                relation = self.edge(self.compound, self.t2, "targets", 100, metadata={"sourceRowId": value})
                self.assertEqual([row["label"] for row in self.search()["results"][0]["targets"]], ["TARGET1"])
                self.assertEqual([row["target"] for row in self.network()["targets"]], ["TARGET1"])
                relation.delete()

    def test_missing_herb_row_id_does_not_claim_a_target_with_the_same_compound(self):
        EvidenceRelation.objects.filter(subject=self.a, relation_type="contains").update(metadata={})
        result = self.search()["results"][0]
        self.assertEqual(result["targets"], [])
        self.assertEqual(len(result["compounds"]), 1)
        self.assertEqual(self.network()["raw"]["herbLinks"], [])

    def test_duplicate_target_rows_deduplicate_entities_but_retain_both_proofs(self):
        self.edge(self.a, self.compound, "contains", 6)
        self.edge(self.compound, self.t1, "targets", 6)
        result = self.search()["results"][0]
        self.assertEqual([row["label"] for row in result["targets"]], ["TARGET1"])
        self.assertEqual(len(result["relations"]), 4)
        network = self.network()
        self.assertEqual(network["summary"]["herbTargetCount"], 1)
        self.assertEqual(len(network["raw"]["herbLinks"]), 2)
        self.assertEqual({row["sourceRecordId"].split(":")[0] for row in network["raw"]["herbLinks"]}, {"2", "6"})

    def test_equal_compound_labels_do_not_substitute_for_entity_identity(self):
        other = KnowledgeEntity.objects.create(entity_type="compound", stable_id="fixture:other-compound-id",
                                               label=self.compound.label, source_release=self.release)
        self.edge(other, self.t2, "targets", 2)
        self.assertEqual([row["label"] for row in self.search()["results"][0]["targets"]], ["TARGET1"])
        self.assertEqual([row["target"] for row in self.network()["targets"]], ["TARGET1"])

    def test_multiple_compounds_keep_their_own_source_rows(self):
        other = self.entity("compound", "Other compound")
        self.edge(self.a, other, "contains", 7)
        self.edge(other, self.t2, "targets", 7)
        result = self.search()["results"][0]
        self.assertEqual({row["label"] for row in result["targets"]}, {"TARGET1", "TARGET2"})
        self.assertEqual(len(result["relations"]), 4)
        raw = self.network()["raw"]["herbLinks"]
        self.assertEqual({(row["herb"], row["target"]) for row in raw}, {("Herb A", "TARGET1"), ("Herb A", "TARGET2")})
        self.assertEqual(len(raw), 2)

    def test_inactive_source_edges_cannot_supply_row_support(self):
        EvidenceRelation.objects.filter(subject=self.a, relation_type="contains").update(is_active=False)
        self.assertEqual(self.search()["results"][0]["targets"], [])
        self.assertEqual(self.network()["raw"]["herbLinks"], [])

    def test_disabled_sources_are_not_reintroduced_by_row_support(self):
        self.release.source.enabled = False
        self.release.source.save(update_fields=["enabled"])
        self.assertEqual(self.search()["results"][0]["matches"], [])
        self.assertEqual(self.network()["raw"]["herbLinks"], [])

    def test_batch_filters_foreign_rows_before_applying_the_candidate_cap(self):
        EvidenceRelation.objects.filter(subject=self.compound, object=self.t1, relation_type="targets").delete()
        EvidenceRelation.objects.bulk_create([
            EvidenceRelation(subject=self.compound, object=self.t2, relation_type="targets",
                             source_release=self.release, source_record_id=f"foreign-row:{row}",
                             metadata={"sourceRowId": row}) for row in range(1000, 2199)
        ])
        self.edge(self.compound, self.t1, "targets", 2)
        result = self.search()["results"][0]
        self.assertEqual([row["label"] for row in result["targets"]], ["TARGET1"])
        self.assertFalse(result["truncated"])

    def test_network_filters_foreign_rows_before_applying_the_candidate_cap(self):
        EvidenceRelation.objects.filter(subject=self.compound, object=self.t1, relation_type="targets").delete()
        self.edge(self.compound, self.t1, "targets", 2)
        result = build_network_pharmacology(user=self.user, herb_query="Herb A", disease_query="Test disease",
                                            row_limit=1, persist=False)
        self.assertEqual(result["summary"]["herbTargetCount"], 1)
        self.assertEqual([row["target"] for row in result["raw"]["herbLinks"]], ["TARGET1"])
        self.assertFalse(result["rawLimits"]["inputRelationsTruncated"]["compoundTargets"])

    def test_database_scope_matches_python_rule_for_json_types_and_sources(self):
        for index, value in enumerate((True, False, "2", 2.0, None, [], {}, 2, -2, 0, 2**40)):
            self.edge(self.compound, self.t2, "targets", 300 + index, metadata={"sourceRowId": value})
        for index, value in enumerate(([], "sourceRowId", 2)):
            self.edge(self.compound, self.t2, "targets", 400 + index, metadata=value)
        for index, metadata in enumerate(({}, {"connector": None}, {"connector": 5}, [], "connector")):
            generic = SourceRelease.objects.create(source=self.release.source, version=f"generic-json-{index}", metadata=metadata)
            self.edge(self.compound, self.t2, "targets", 500 + index, release=generic, metadata={})
        # Include zero, negative and 64-bit row IDs: the original int rule did
        # not impose a new sign/range policy, and this fix must preserve it.
        for row in (-2, 0, 2**40):
            self.edge(self.a, self.compound, "contains", row)
        herb_edges = list(EvidenceRelation.objects.filter(subject=self.a).select_related("source_release"))
        targets = EvidenceRelation.objects.filter(relation_type="targets").select_related("source_release")
        expected = {edge.pk for edge in targets if HerbRowSupport(herb_edges).for_target(edge)}
        self.assertEqual(set(supported_target_queryset(targets, herb_edges).values_list("pk", flat=True)), expected)

    def test_invalid_row_types_cannot_occupy_the_network_limit(self):
        EvidenceRelation.objects.filter(subject=self.compound, relation_type="targets").delete()
        for index, value in enumerate((2.0, "2", True, None)):
            self.edge(self.compound, self.t2, "targets", 600 + index, metadata={"sourceRowId": value})
        self.edge(self.compound, self.t1, "targets", 2)
        result = build_network_pharmacology(user=self.user, herb_query="Herb A", disease_query="Test disease",
                                            row_limit=1, persist=False)
        self.assertEqual(result["summary"]["herbTargetCount"], 1)
        self.assertEqual([row["target"] for row in result["raw"]["herbLinks"]], ["TARGET1"])
        self.assertFalse(result["rawLimits"]["inputRelationsTruncated"]["compoundTargets"])

    def test_actual_valid_annotation_overflow_still_sets_batch_truncation(self):
        generic = SourceRelease.objects.create(source=self.release.source, version="generic-overflow")
        EvidenceRelation.objects.bulk_create([
            EvidenceRelation(subject=self.compound, object=self.t2, relation_type="targets",
                             source_release=generic, source_record_id=f"generic-overflow:{row}")
            for row in range(1200)
        ])
        result = self.search()["results"][0]
        self.assertEqual({row["label"] for row in result["targets"]}, {"TARGET1", "TARGET2"})
        self.assertEqual(sum(row["relationType"] == "targets" for row in result["relations"]), 1200)
        self.assertTrue(result["truncated"])

    def test_actual_valid_annotation_overflow_still_sets_network_truncation(self):
        generic = SourceRelease.objects.create(source=self.release.source, version="generic-network-overflow")
        self.edge(self.compound, self.t2, "targets", 700, release=generic, metadata={})
        result = build_network_pharmacology(user=self.user, herb_query="Herb A", disease_query="Test disease",
                                            row_limit=1, persist=False)
        self.assertEqual(result["summary"]["herbTargetCount"], 1)
        self.assertTrue(result["rawLimits"]["inputRelationsTruncated"]["compoundTargets"])

    def test_generic_annotations_work_without_any_valid_legacy_herb_rows(self):
        EvidenceRelation.objects.filter(subject=self.a).update(metadata={})
        generic = SourceRelease.objects.create(source=self.release.source, version="generic-no-legacy-rows")
        self.edge(self.compound, self.t2, "targets", 800, release=generic, metadata={})
        self.assertEqual([row["label"] for row in self.search()["results"][0]["targets"]], ["TARGET2"])
        self.assertEqual([row["target"] for row in self.network()["raw"]["herbLinks"]], ["TARGET2"])
