"""Main-generated golden data and boundary tests for network statistic parity."""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease
from apps.core.services.network_pharmacology import STATISTICS_VERSION, build_network_pharmacology


class NetworkStatisticsParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fixture = json.loads((Path(__file__).parent / "fixtures" / "main_network_statistics.json").read_text())
        cls.user = get_user_model().objects.create_user(username="network-statistics-owner")
        cls.releases = {}
        for slug in ("fixture", "fixture-duplicate"):
            source = DataSource.objects.create(slug=slug, name=slug)
            cls.releases[slug] = SourceRelease.objects.create(
                source=source, version=f"{slug}-v1", checksum_sha256="a" * 64,
            )
        cls.herb = cls.entity("herb", "herb:fixture", cls.fixture["herbs"][0])
        cls.disease = cls.entity("disease", "disease:fixture", cls.fixture["disease"])
        cls.compounds = {}
        cls.targets = {}
        cls.pathways = {}
        for row in cls.fixture["herbRows"]:
            compound = cls.compounds.get(row["component"])
            if compound is None:
                compound = cls.entity("compound", f"compound:{row['component']}", row["component"])
                cls.compounds[row["component"]] = compound
                cls.relation("contains", cls.herb, compound, f"contains:{compound.label}")
            cls.targets.setdefault(row["target"], None)
        for row in cls.fixture["diseaseTargetRows"] + cls.fixture["diseaseHerbRows"]:
            cls.targets.setdefault(row["target"], None)
        for label in cls.targets:
            cls.targets[label] = cls.entity("protein", f"protein:{label}", label)
        for index, row in enumerate(cls.fixture["herbRows"]):
            cls.relation(
                "targets", cls.compounds[row["component"]], cls.targets[row["target"]],
                f"targets:{index}", release=cls.releases[row["source"]],
            )
        for index, row in enumerate(cls.fixture["diseaseTargetRows"]):
            cls.relation("disease_target", cls.disease, cls.targets[row["target"]], f"disease:{index}")
        for index, row in enumerate(cls.fixture["diseaseHerbRows"]):
            cls.relation(
                "disease_herb_target", cls.disease, cls.targets[row["target"]], f"direct:{index}",
                metadata={"herbStableId": cls.herb.stable_id, "herbLabel": cls.herb.label},
            )
        for annotation in cls.fixture["annotations"]:
            for pathway in annotation["pathways"]:
                entity = cls.entity("pathway", f"pathway:{pathway['name']}", pathway["name"])
                cls.pathways[pathway["name"]] = entity
                cls.relation(
                    "participatesin", cls.targets[annotation["symbol"]], entity,
                    f"pathway:{annotation['symbol']}:{pathway['name']}",
                )

    @classmethod
    def entity(cls, kind, stable_id, label):
        return KnowledgeEntity.objects.create(
            entity_type=kind, stable_id=stable_id, label=label, source_release=cls.releases["fixture"],
        )

    @classmethod
    def relation(cls, kind, subject, object_, record_id, *, release=None, metadata=None):
        return EvidenceRelation.objects.create(
            source_release=release or cls.releases["fixture"], source_record_id=record_id,
            subject=subject, object=object_, relation_type=kind, evidence_type="golden-synthetic-fixture",
            metadata=metadata or {},
        )

    def result(self, *, persist=False, herb=None, disease=None, **kwargs):
        return build_network_pharmacology(
            user=self.user, herb_query=herb or self.herb.label, disease_query=disease or self.disease.label,
            persist=persist, **kwargs,
        )

    def test_main_generated_statistics_and_target_union_match_on_equivalent_evidence(self):
        result = self.result(persist=True)
        expected = self.fixture["expected"]
        for key, value in expected["summary"].items():
            self.assertEqual(result["summary"][key], value, key)
        for key, value in expected["charts"].items():
            self.assertEqual(result["charts"][key], value, key)
        self.assertEqual(result["charts"]["overlap"], [
            {"name": "中药靶点", "value": 3}, {"name": "疾病靶点", "value": 3},
            {"name": "严格交集", "value": 2}, {"name": "直接关联", "value": 2},
        ])
        by_target = {row["target"]: row for row in result["targets"]}
        self.assertEqual(set(by_target), {"TP53", "AKT1", "FOXO3"})
        self.assertEqual(len(result["targets"]), 3)
        for row in expected["targetRows"]:
            for key, value in row.items():
                actual = by_target[row["target"]][key]
                if key == "matchType":
                    actual = actual.replace("—", "-")
                self.assertEqual(actual, value, f"{row['target']}.{key}")
        self.assertEqual(by_target["TP53"]["matchType"], "严格交集")
        task = AnalysisTask.objects.get(pk=result["taskId"])
        self.assertEqual(task.owner, self.user)
        self.assertEqual(task.created_by, self.user)
        self.assertEqual(task.input_parameters["statisticsVersion"], STATISTICS_VERSION)
        self.assertEqual(task.result, {key: value for key, value in result.items() if key != "taskId"})
        self.assertEqual(set(task.source_releases.all()), set(self.releases.values()))
        self.assertEqual(
            {(record["sourceSlug"], record["sourceVersion"]) for record in by_target["TP53"]["sources"]},
            {("fixture", "fixture-v1"), ("fixture-duplicate", "fixture-duplicate-v1")},
        )

    def test_duplicate_direct_evidence_counts_support_but_not_candidates(self):
        self.relation(
            "disease_herb_target", self.disease, self.targets["TP53"], "direct:duplicate",
            metadata={"herbStableId": self.herb.stable_id},
        )
        result = self.result()
        self.assertEqual(result["summary"]["strictIntersectionCount"], 2)
        self.assertEqual(result["summary"]["directAssociationTargetCount"], 2)
        self.assertEqual(result["summary"]["candidateTargetCount"], 3)
        tp53 = next(row for row in result["targets"] if row["target"] == "TP53")
        self.assertEqual(tp53["directEvidenceCount"], 2)
        self.assertEqual(tp53["matchType"], "严格交集")
        self.assertEqual(result["charts"]["components"], self.fixture["expected"]["charts"]["components"])

    def test_direct_only_targets_do_not_fabricate_component_or_pathway_counts(self):
        EvidenceRelation.objects.filter(subject=self.disease).exclude(object=self.targets["FOXO3"]).delete()
        direct_relation = EvidenceRelation.objects.get(subject=self.disease, object=self.targets["FOXO3"])
        direct_relation.metadata = {"herbStableId": self.herb.stable_id}
        direct_relation.save(update_fields=["metadata"])
        result = self.result()
        self.assertEqual([row["target"] for row in result["targets"]], ["FOXO3"])
        self.assertEqual(result["targets"][0]["herbs"], [self.herb.label])
        self.assertEqual(result["summary"]["strictIntersectionCount"], 0)
        self.assertEqual(result["summary"]["directAssociationTargetCount"], 1)
        self.assertEqual(result["summary"]["componentCount"], 3)
        self.assertEqual(result["summary"]["pathwayCount"], 0)
        self.assertEqual(result["charts"]["components"], [])
        self.assertEqual(result["charts"]["pathways"], [])

    def test_direct_herb_label_without_a_selected_stable_id_is_ignored(self):
        EvidenceRelation.objects.filter(subject=self.disease).exclude(object=self.targets["FOXO3"]).delete()
        direct_relation = EvidenceRelation.objects.get(subject=self.disease, object=self.targets["FOXO3"])
        direct_relation.metadata = {"herbLabel": self.herb.label}
        direct_relation.save(update_fields=["metadata"])

        result = self.result()

        self.assertEqual(result["targets"], [])
        self.assertEqual(result["summary"]["directAssociationTargetCount"], 0)

    def test_same_label_unselected_herb_id_does_not_match_selected_herb(self):
        EvidenceRelation.objects.filter(subject=self.disease).exclude(object=self.targets["FOXO3"]).delete()
        unselected_same_label = self.entity("herb", "herb:inactive-duplicate", self.herb.label)
        unselected_same_label.is_active = False
        unselected_same_label.save(update_fields=["is_active"])
        direct_relation = EvidenceRelation.objects.get(subject=self.disease, object=self.targets["FOXO3"])
        direct_relation.metadata = {
            "herbStableId": unselected_same_label.stable_id,
            "herbLabel": self.herb.label,
        }
        direct_relation.save(update_fields=["metadata"])

        result = self.result()

        self.assertEqual(result["targets"], [])
        self.assertEqual(result["summary"]["directAssociationTargetCount"], 0)

    def test_direct_only_pathway_annotations_keep_real_versions_and_hide_disabled_sources(self):
        EvidenceRelation.objects.filter(subject=self.disease).exclude(object=self.targets["FOXO3"]).delete()
        source = DataSource.objects.create(slug="direct-pathway-source", name="直接候选通路合成测试来源")
        release = SourceRelease.objects.create(
            source=source, version="pathways-v7", checksum_sha256="b" * 64,
        )
        pathway = KnowledgeEntity.objects.create(
            entity_type="pathway", stable_id="pathway:foxo-signal", label="FOXO signalling",
            source_release=release,
        )
        self.relation(
            "participatesin", self.targets["FOXO3"], pathway, "direct-pathway:1", release=release,
        )
        result = self.result(persist=True)
        self.assertEqual(result["summary"]["candidateTargetCount"], 1)
        self.assertEqual(result["summary"]["pathwayCount"], 1)
        self.assertEqual(result["charts"]["pathways"], [{"name": "FOXO signalling", "targets": 1}])
        self.assertEqual(result["targets"][0]["pathways"], ["FOXO signalling"])
        annotation = next(
            record for record in result["targets"][0]["sources"] if record["relationType"] == "participatesin"
        )
        self.assertEqual(annotation["sourceSlug"], source.slug)
        self.assertEqual(annotation["sourceVersion"], "pathways-v7")
        task = AnalysisTask.objects.get(pk=result["taskId"])
        self.assertIn(release, task.source_releases.all())
        source.enabled = False
        source.save(update_fields=["enabled"])
        hidden = self.result(persist=True)
        self.assertEqual(hidden["summary"]["candidateTargetCount"], 1)
        self.assertEqual(hidden["summary"]["pathwayCount"], 0)
        self.assertEqual(hidden["targets"][0]["pathways"], [])
        self.assertEqual(hidden["charts"]["pathways"], [])
        self.assertNotIn(release, AnalysisTask.objects.get(pk=hidden["taskId"]).source_releases.all())
        task.refresh_from_db()
        self.assertEqual(task.result["targets"][0]["pathways"], ["FOXO signalling"])
        self.assertIn(release, task.source_releases.all())

    def test_exact_queries_and_stable_target_identity_remain_required(self):
        same_label = self.entity("protein", "protein:another-tp53", "TP53")
        EvidenceRelation.objects.filter(subject=self.disease, object=self.targets["TP53"]).update(object=same_label)
        result = self.result()
        self.assertEqual(result["summary"]["strictIntersectionCount"], 1)
        self.assertEqual(result["summary"]["directAssociationTargetCount"], 2)
        tp53 = next(row for row in result["targets"] if row["target"] == "TP53")
        self.assertEqual(tp53["matchType"], "疾病—中药直接关联")
        self.assertEqual(tp53["components"], [])
        self.assertEqual(result["charts"]["components"], [{"name": "Alpha", "targets": 1}])
        partial = self.result(herb="黄", disease="肺纤维")
        self.assertEqual(partial["summary"]["matchedHerbs"], [])
        self.assertEqual(partial["summary"]["matchedDiseases"], [])
        self.assertEqual(partial["targets"], [])

    def test_tied_component_counts_and_equal_target_labels_have_stable_order(self):
        a_target = self.entity("protein", "protein:a-shared", "SHARED")
        z_target = self.entity("protein", "protein:z-shared", "SHARED")
        for name, target in (("Zeta", z_target), ("Gamma", a_target)):
            compound = self.entity("compound", f"compound:{name}", name)
            self.relation("contains", self.herb, compound, f"contains:{name}")
            self.relation("targets", compound, target, f"target:{name}")
            self.relation("disease_target", self.disease, target, f"disease:{name}")
        result = self.result()
        self.assertEqual(result["charts"]["components"], [
            {"name": "Alpha", "targets": 2}, {"name": "Beta", "targets": 1},
            {"name": "Gamma", "targets": 1}, {"name": "Zeta", "targets": 1},
        ])
        same_labels = [row for row in result["targets"] if row["target"] == "SHARED"]
        self.assertEqual([row["components"] for row in same_labels], [["Gamma"], ["Zeta"]])
        self.assertEqual(result, self.result())

    def test_target_payload_limit_keeps_full_candidate_summary_and_component_counts(self):
        EvidenceRelation.objects.filter(subject=self.disease).delete()
        targets = [KnowledgeEntity(
            entity_type="protein", stable_id=f"protein:bulk-{index:04}", label=f"TARGET{index:04}",
            source_release=self.releases["fixture"],
        ) for index in range(1001)]
        KnowledgeEntity.objects.bulk_create(targets)
        EvidenceRelation.objects.bulk_create([
            EvidenceRelation(
                source_release=self.releases["fixture"], source_record_id=f"bulk:{kind}:{index}",
                subject=self.disease if kind == "disease_target" else self.compounds["Alpha"],
                object=target, relation_type=kind, evidence_type="golden-synthetic-fixture",
            ) for kind in ("targets", "disease_target") for index, target in enumerate(targets)
        ])
        result = self.result()
        self.assertEqual(result["summary"]["candidateTargetCount"], 1001)
        self.assertEqual(result["summary"]["strictIntersectionCount"], 1001)
        self.assertEqual(len(result["targets"]), 1000)
        self.assertTrue(result["limits"]["targetsTruncated"])
        self.assertEqual(result["charts"]["components"], [{"name": "Alpha", "targets": 1001}])
        self.assertEqual(result["summary"]["pathwayCount"], 0)
