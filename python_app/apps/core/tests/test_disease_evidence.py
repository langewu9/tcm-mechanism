import hashlib
import ast
import sqlite3
import tempfile
from contextlib import closing
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import (
    AnalysisTask,
    DataSource,
    EvidenceRelation,
    KnowledgeEntity,
    MedicalCaseAuditEvent,
    SourceRelease,
    SyncRun,
)
from apps.core.services.disease_names import expand_disease_queries


BASELINE_DISEASE_HERB_TARGET_ROWS = [
    {
        "disease": "肺纤维化", "herb": "甘草", "target": "TP53",
        "sourceRecordId": "direct:one", "herbStableId": "herb:two",
        "targetStableId": "gene:one", "sourceRelease": "evidence-v1",
    },
    {
        "disease": "肺纤维化", "herb": "甘草", "target": "TP53",
        "sourceRecordId": "direct:duplicate", "herbStableId": "herb:two",
        "targetStableId": "gene:one", "sourceRelease": "evidence-v2",
    },
]
BASELINE_DISEASE_TARGET_ROWS = [
    {"disease": "肺纤维化", "target": "TP53", "targetStableId": "gene:one", "sourceRecordId": "target:one"},
    {"disease": "肺纤维化", "target": "TP53", "targetStableId": "protein:two", "sourceRecordId": "target:two"},
]
MAIN_DATA_SERVICE_SHA256 = "7fae7384a64b236d787696fbe1288c583d680df59054e8592cd93f60897aa6f9"


class DiseaseEvidenceSearchTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="disease-evidence-reader", password="test-password-123"
        )
        cls.disease_source, cls.disease_release = cls.source_release("disease-fixture", "disease-v1")
        cls.evidence_source, cls.evidence_release = cls.source_release("evidence-fixture", "evidence-v1")
        cls.second_evidence_source, cls.second_evidence_release = cls.source_release(
            "evidence-fixture-second", "evidence-v2"
        )
        cls.disabled_source, cls.disabled_release = cls.source_release(
            "disabled-fixture", "disabled-v1", enabled=False
        )

        cls.disease = cls.entity(
            "disease", "EFO:0000768", "肺纤维化", source_release=cls.disease_release,
            synonyms=["Pulmonary fibrosis"],
        )
        cls.same_label_disease = cls.entity(
            "disease", "DOID:0000001", "肺纤维化", source_release=cls.disease_release,
        )
        cls.isolated_disease = cls.entity(
            "disease", "EFO:isolated", "孤立疾病", source_release=cls.disease_release,
        )
        cls.disabled_disease = cls.entity(
            "disease", "disabled:disease", "Pulmonary fibrosis disabled",
            source_release=cls.disabled_release, synonyms=["Pulmonary fibrosis"],
        )
        cls.dictionary_key_only_diseases = [
            KnowledgeEntity(
                entity_type="disease",
                stable_id=f"dictionary-key-only:{index:02d}",
                label=f"00 unrelated key hit {index:02d}",
                synonyms={"Pulmonary fibrosis": "not a synonym value"},
                source_release=cls.disease_release,
            )
            for index in range(21)
        ]
        KnowledgeEntity.objects.bulk_create(cls.dictionary_key_only_diseases)
        cls.herb_one = cls.entity("herb", "herb:one", "甘草", source_release=cls.evidence_release)
        cls.herb_two = cls.entity("herb", "herb:two", "甘草", source_release=cls.evidence_release)
        cls.disabled_herb = cls.entity("herb", "herb:disabled", "甘草", source_release=cls.disabled_release)
        cls.target_one = cls.entity("gene", "gene:one", "TP53", source_release=cls.evidence_release)
        cls.target_two = cls.entity("protein", "protein:two", "TP53", source_release=cls.evidence_release)

        cls.relation(cls.disease, cls.herb_one, "disease_herb", "herb:one")
        cls.relation(cls.disease, cls.herb_two, "disease_herb", "herb:two")
        for row in BASELINE_DISEASE_HERB_TARGET_ROWS:
            target = cls.target_one if row["targetStableId"] == cls.target_one.stable_id else cls.target_two
            evidence_release = (
                cls.evidence_release if row["sourceRelease"] == cls.evidence_release.version
                else cls.second_evidence_release
            )
            cls.relation(
                cls.disease, target, "disease_herb_target", row["sourceRecordId"],
                source_release=evidence_release,
                metadata={"herbStableId": row["herbStableId"]},
            )
        for row in BASELINE_DISEASE_TARGET_ROWS:
            target = cls.target_one if row["targetStableId"] == cls.target_one.stable_id else cls.target_two
            cls.relation(cls.disease, target, "disease_target", row["sourceRecordId"])

    @classmethod
    def source_release(cls, slug, version, enabled=True):
        source = DataSource.objects.create(slug=slug, name=slug, enabled=enabled)
        return source, SourceRelease.objects.create(source=source, version=version)

    @classmethod
    def entity(cls, entity_type, stable_id, label, **kwargs):
        return KnowledgeEntity.objects.create(
            entity_type=entity_type, stable_id=stable_id, label=label, **kwargs
        )

    @classmethod
    def relation(cls, subject, object_, relation_type, record_id, **kwargs):
        return EvidenceRelation.objects.create(
            subject=subject,
            object=object_,
            relation_type=relation_type,
            evidence_type="fixture",
            source_release=kwargs.pop("source_release", cls.evidence_release),
            source_record_id=record_id,
            **kwargs,
        )

    def search(self, query="肺纤维化"):
        return self.client.get(reverse("disease-evidence-search"), {"query": query})

    def authenticate(self):
        self.client.force_authenticate(self.user)

    def test_requires_authentication_and_uses_the_shared_query_validation_envelope(self):
        self.assertEqual(self.search().status_code, 401)
        self.authenticate()
        blank = self.search("   ")
        self.assertEqual(blank.status_code, 400)
        self.assertEqual(blank.data["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(self.search("x" * 121).status_code, 400)

    def test_alias_expansion_and_visible_graph_return_distinct_ids_and_all_evidence_rows(self):
        self.authenticate()
        response = self.search()
        self.assertEqual(response.status_code, 200)
        data = response.data

        self.assertEqual(data["query"], "肺纤维化")
        self.assertEqual(data["expandedQueries"], expand_disease_queries("肺纤维化"))
        self.assertEqual(data["aliasSourceCommit"], "078d374")
        self.assertEqual(len(data["matches"]), 2)
        self.assertTrue(data["ambiguous"])
        self.assertEqual({row["id"] for row in data["matches"]}, {self.disease.pk, self.same_label_disease.pk})
        self.assertNotIn(self.disabled_disease.pk, {row["id"] for row in data["matches"]})

        self.assertEqual([row["id"] for row in data["herbs"]], [self.herb_one.pk, self.herb_two.pk])
        self.assertEqual({row["id"] for row in data["targets"]}, {self.target_one.pk, self.target_two.pk})
        self.assertEqual(len(data["relations"]), 6)
        self.assertEqual(data["counts"], {
            "diseases": 2, "herbs": 2, "targets": 2, "links": 6, "relations": 6,
        })
        self.assertEqual(data["limits"], {"maxMatches": 20, "maxRelations": 1200})
        self.assertFalse(data["truncated"])

        direct_rows = [row for row in data["links"] if row["relationType"] == "disease_herb_target"]
        self.assertEqual(len(direct_rows), 2)
        self.assertEqual(
            {row["sourceRecordId"]: row["herb"] for row in direct_rows},
            {"direct:one": "甘草", "direct:duplicate": "甘草"},
        )
        self.assertTrue(all(row["target"] == "TP53" for row in direct_rows))
        self.assertEqual(
            {(row["sourceSlug"], row["sourceRecordId"]) for row in direct_rows},
            {("evidence-fixture", "direct:one"), ("evidence-fixture-second", "direct:duplicate")},
        )
        self.assertEqual(len([row for row in data["relations"] if row["relationType"] == "disease_target"]), 2)
        self.assertEqual(len([row for row in data["relations"] if row["relationType"] == "disease_herb_target"]), 2)

    def test_synonym_dictionary_keys_do_not_become_disease_matches_or_hide_later_values(self):
        self.authenticate()
        response = self.search()
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["id"] for row in response.data["matches"]}, {self.disease.pk, self.same_label_disease.pk})
        self.assertFalse(response.data["truncated"])

    def test_invalid_metadata_inactive_sources_and_relation_entity_type_mismatches_are_ignored(self):
        self.relation(
            self.disease, self.target_one, "disease_herb_target", "direct:disabled-herb",
            metadata={"herbStableId": self.disabled_herb.stable_id, "herbLabel": "甘草"},
        )
        self.relation(
            self.disease, self.target_two, "disease_herb_target", "direct:invalid-herb",
            metadata={"herbStableId": "herb:missing", "herbLabel": "甘草"},
        )
        self.relation(
            self.disease, self.target_one, "disease_herb_target", "direct:list-metadata",
            metadata=[{"herbStableId": self.herb_one.stable_id}],
        )
        self.relation(
            self.disease, self.target_one, "disease_herb_target", "direct:invalid-list",
            metadata={"herbStableId": [self.herb_one.stable_id], "herbLabel": "甘草"},
        )
        self.relation(
            self.disease, self.target_one, "disease_herb_target", "direct:invalid-number",
            metadata={"herbStableId": 123, "herbLabel": "甘草"},
        )
        inactive_herb = self.entity(
            "herb", "herb:inactive", "停用中药", source_release=self.evidence_release, is_active=False
        )
        inactive_target = self.entity(
            "gene", "gene:inactive", "停用靶点", source_release=self.evidence_release, is_active=False
        )
        self.relation(self.disease, inactive_herb, "disease_herb", "inactive-object")
        self.relation(self.disease, inactive_target, "disease_target", "inactive-target")
        self.relation(self.disease, self.target_one, "disease_target", "inactive-relation", is_active=False)
        self.relation(
            self.disease, self.target_one, "disease_target", "disabled-source",
            source_release=self.disabled_release,
        )
        self.relation(self.disease, self.target_one, "disease_herb", "wrong-herb-object-type")
        self.relation(self.disease, self.herb_one, "disease_target", "wrong-target-object-type")

        self.authenticate()
        data = self.search().data
        self.assertEqual(len(data["relations"]), 11)
        self.assertEqual(data["counts"], {
            "diseases": 2, "herbs": 2, "targets": 2, "links": 11, "relations": 11,
        })
        direct_rows = [row for row in data["links"] if row["relationType"] == "disease_herb_target"]
        self.assertEqual(len(direct_rows), 7)
        self.assertEqual(
            {row["sourceRecordId"]: row["herb"] for row in direct_rows},
            {"direct:one": "甘草", "direct:duplicate": "甘草", "direct:disabled-herb": "",
             "direct:invalid-herb": "", "direct:list-metadata": "", "direct:invalid-list": "",
             "direct:invalid-number": ""},
        )
        relation_ids = {row["sourceRecordId"] for row in data["relations"]}
        for ignored_id in (
            "inactive-object", "inactive-target", "inactive-relation", "disabled-source",
            "wrong-herb-object-type", "wrong-target-object-type",
        ):
            self.assertNotIn(ignored_id, relation_ids)
        self.assertNotIn(inactive_herb.pk, {row["id"] for row in data["herbs"]})
        self.assertNotIn(inactive_target.pk, {row["id"] for row in data["targets"]})

    def test_no_results_returns_empty_visible_summary(self):
        self.authenticate()
        response = self.search("completely unrelated disease")
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(data["matches"], [])
        self.assertEqual(data["herbs"], [])
        self.assertEqual(data["targets"], [])
        self.assertEqual(data["relations"], [])
        self.assertEqual(data["links"], [])
        self.assertEqual(data["counts"], {"diseases": 0, "herbs": 0, "targets": 0, "links": 0, "relations": 0})

    def test_disease_without_valid_relations_returns_match_and_empty_evidence(self):
        self.authenticate()
        response = self.search("孤立疾病")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.data["matches"]], [self.isolated_disease.pk])
        self.assertEqual(response.data["relations"], [])
        self.assertEqual(response.data["links"], [])
        self.assertEqual(response.data["counts"], {
            "diseases": 1, "herbs": 0, "targets": 0, "links": 0, "relations": 0,
        })

    def test_search_is_read_only_and_matches_main_sqlite_sample_projection(self):
        self.authenticate()
        before = (AnalysisTask.objects.count(), SyncRun.objects.count(), MedicalCaseAuditEvent.objects.count())
        response = self.search()
        after = (AnalysisTask.objects.count(), SyncRun.objects.count(), MedicalCaseAuditEvent.objects.count())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(after, before)

        # Execute main's original search_disease function against its cache schema,
        # using synthetic rows rather than treating the migrated result as a golden.
        repository_root = Path(__file__).resolve().parents[4]
        source_path = repository_root / "backend" / "data_service.py"
        # Git may check out CRLF on Windows; compare canonical source bytes.
        source_bytes = source_path.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(source_bytes).hexdigest(), MAIN_DATA_SERVICE_SHA256)
        module = ast.parse(source_bytes.decode("utf-8"), filename=str(source_path))
        original_function = next(
            node for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "search_disease"
        )
        namespace = {
            "sqlite3": sqlite3,
            "_like": lambda value: f"%{value.strip()}%",
        }
        exec(compile(ast.Module(body=[original_function], type_ignores=[]), str(source_path), "exec"), namespace)

        synthetic_disease_herb_target_rows = [
            (row["disease"], row["herb"], row["target"])
            for row in BASELINE_DISEASE_HERB_TARGET_ROWS
        ]
        synthetic_disease_target_rows = [
            (row["disease"], row["target"])
            for row in BASELINE_DISEASE_TARGET_ROWS
        ]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "synthetic-main-cache.sqlite"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("CREATE TABLE disease_herb_target (disease TEXT, herb TEXT, target TEXT)")
                connection.execute("CREATE TABLE disease_target (disease TEXT, target TEXT)")
                connection.executemany(
                    "INSERT INTO disease_herb_target VALUES (?, ?, ?)",
                    synthetic_disease_herb_target_rows,
                )
                connection.executemany(
                    "INSERT INTO disease_target VALUES (?, ?)", synthetic_disease_target_rows
                )

            opened_connections = []

            def open_synthetic_cache():
                connection = sqlite3.connect(database)
                connection.row_factory = sqlite3.Row
                opened_connections.append(connection)
                return connection

            namespace["_cache"] = open_synthetic_cache
            try:
                legacy = namespace["search_disease"]("肺纤维化")
            finally:
                for connection in opened_connections:
                    connection.close()

        direct_rows = [row for row in response.data["links"] if row["relationType"] == "disease_herb_target"]
        projected_rows = [
            (row["disease"], row["herb"], row["target"])
            for row in direct_rows
        ]
        self.assertEqual(set(legacy["links"][0]), {"疾病", "中药", "靶点基因"})
        self.assertEqual(
            Counter((row["疾病"], row["中药"], row["靶点基因"]) for row in legacy["links"]),
            Counter(synthetic_disease_herb_target_rows),
        )
        self.assertEqual(Counter(projected_rows), Counter(synthetic_disease_herb_target_rows))
        self.assertEqual(legacy["herbs"], ["甘草"])
        self.assertEqual(legacy["targets"], ["TP53"])
        self.assertEqual(legacy["counts"]["links"], len(BASELINE_DISEASE_HERB_TARGET_ROWS))
        self.assertEqual(response.data["counts"]["links"], len(BASELINE_DISEASE_HERB_TARGET_ROWS) + 4)
        self.assertEqual(response.data["counts"]["herbs"], 2)  # same legacy herb label, two canonical IDs
        self.assertEqual(response.data["counts"]["targets"], 2)  # same legacy target label, two canonical IDs

    def test_plus_one_truncation_checks_match_and_relation_limits(self):
        self.authenticate()
        with patch("apps.core.services.disease_evidence.MAX_MATCHES", 1):
            match_data = self.search().data
        self.assertEqual(len(match_data["matches"]), 1)
        self.assertEqual(match_data["counts"]["diseases"], 1)
        self.assertTrue(match_data["truncated"])
        self.assertEqual(match_data["limits"]["maxMatches"], 1)

        with patch("apps.core.services.disease_evidence.MAX_RELATIONS", 1):
            relation_data = self.search().data
        self.assertEqual(len(relation_data["relations"]), 1)
        self.assertEqual(relation_data["counts"]["relations"], 1)
        self.assertEqual(relation_data["counts"]["links"], 1)
        self.assertTrue(relation_data["truncated"])
        self.assertEqual(relation_data["limits"]["maxRelations"], 1)
