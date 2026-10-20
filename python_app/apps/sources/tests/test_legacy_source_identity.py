import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.core.models import DataSource, EntityIdentifier, EvidenceRelation, KnowledgeEntity, SyncRun
from apps.core.services.catalog_analysis import save_catalog_analysis
from apps.core.services.herb_evidence import batch_herb_component_evidence
from apps.sources.connectors.sqlite_tcm import SQLiteSourceError, iter_configured_rows, validate_sqlite_source_config
from apps.sources.legacy_identity import read_identity_record
from apps.sources.sqlite_sync import _row_entities_and_relations, _stable_id, apply_sqlite_sync, preview_sqlite_sync


def record(row=2, target_id="T1", **identity):
    return {"schemaVersion": "legacy-source-identity-1", "workbookSha256": "a" * 64,
            "sheet": "Sheet1", "sourceRow": row,
            "identity": {"herbId": "H1", "compoundId": "C1", "targetId": target_id,
                         "targetSymbol": "Tp53", "uniprot": "P04637", "pubchem": "CID:123", **identity},
            "rawFields": {"Herb ID": "H1", "Target ID": target_id, "Symbol": "Tp53"}}


class LegacySourceIdentityTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        settings = override_settings(SQLITE_SOURCE_ROOT=str(self.root))
        settings.enable(); self.addCleanup(settings.disable)
        self.path = self.root / "fixture.sqlite3"
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE evidence (herb TEXT, compound TEXT, target TEXT, extra TEXT)")
        self.source = DataSource.objects.create(slug="identity-fixture", name="Synthetic identity assertions", configuration={
            "connector": "sqlite-herb-compound-target", "databaseFile": self.path.name, "table": "evidence",
            "herbColumn": "herb", "compoundColumn": "compound", "targetColumn": "target",
            "targetCellMode": "single", "rowMetadataColumn": "extra"})

    def insert(self, value, label="Tp53"):
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT INTO evidence(rowid, herb, compound, target, extra) VALUES (?, ?, ?, ?, ?)",
                               (value["sourceRow"], "测试中药", "测试成分", label, json.dumps(value)))

    def sync(self):
        run = SyncRun.objects.create(source=self.source)
        preview_sqlite_sync(run)
        apply_sqlite_sync(run)
        return run

    def test_same_name_different_provider_ids_stay_separate_and_unverified(self):
        self.insert(record())
        self.insert(record(row=3, target_id="T2", uniprot="P14780"))
        run = self.sync()
        targets = list(KnowledgeEntity.objects.filter(entity_type="protein"))
        self.assertEqual(len(targets), 2)
        self.assertEqual({item.metadata["sourceEntityId"] for item in targets}, {"T1", "T2"})
        self.assertEqual({item.organism for item in targets}, {""})
        self.assertTrue(all(item.metadata["identifierStatus"] == "unverified_symbol" for item in targets))
        self.assertTrue(all(item.metadata["sourceReferences"][0]["status"] == "source_reported_unverified" for item in targets))
        self.assertEqual(EntityIdentifier.objects.count(), 0)
        self.assertEqual(EvidenceRelation.objects.count(), 4)
        self.assertEqual(run.records_seen, 2)

    def test_provider_ids_are_case_sensitive(self):
        self.insert(record(target_id="T1"))
        self.insert(record(row=3, target_id="t1"))
        self.sync()
        self.assertEqual(KnowledgeEntity.objects.filter(entity_type="protein").count(), 2)

    def test_source_identifiers_cannot_collide_with_legacy_name_identifiers(self):
        entities, _ = _row_entities_and_relations(self.source, ("herb", 2, "测试中药", "测试成分", "Tp53", record(target_id="t1")))
        target = next(item for item in entities if item["entity_type"] == "protein")
        self.assertNotEqual(target["stable_id"], _stable_id(self.source, "target", "source-id:t1"))
        self.assertIn(":target:id:", target["stable_id"])

    def test_identity_policy_change_invalidates_preview_and_versions_the_release(self):
        self.insert(record())
        with patch("apps.sources.sqlite_sync.IDENTITY_POLICY", "older-test-policy"):
            previous = self.sync()
            pending = SyncRun.objects.create(source=self.source)
            preview_sqlite_sync(pending)
        with self.assertRaisesRegex(ValidationError, "变化"):
            apply_sqlite_sync(pending)
        current = self.sync()
        self.assertNotEqual(previous.release_id, current.release_id)
        self.assertFalse(EvidenceRelation.objects.filter(source_release=previous.release, is_active=True).exists())
        self.assertEqual(KnowledgeEntity.objects.filter(is_active=True).count(), 3)

    def test_same_source_id_with_conflicting_assertions_blocks_preview_without_partial_import(self):
        self.insert(record())
        self.insert(record(row=3, uniprot="P14780"))
        run = SyncRun.objects.create(source=self.source)
        with self.assertRaisesRegex(ValidationError, "冲突"):
            preview_sqlite_sync(run)
        self.assertEqual(KnowledgeEntity.objects.count(), 0)
        self.assertEqual(EvidenceRelation.objects.count(), 0)

    def test_repeated_apply_keeps_entity_ids_and_source_assertions(self):
        self.insert(record())
        self.sync()
        first = list(KnowledgeEntity.objects.values_list("pk", "stable_id", "metadata"))
        run = self.sync()
        self.assertEqual(first, list(KnowledgeEntity.objects.values_list("pk", "stable_id", "metadata")))
        self.assertEqual(run.preview_summary["entitiesUnchanged"], 3)

    def test_origin_and_original_fields_are_retained_in_evidence_and_saved_graph(self):
        original = record()
        self.insert(original); self.sync()
        relation = EvidenceRelation.objects.first()
        self.assertEqual(relation.metadata["sourceOrigin"]["sourceRow"], 2)
        self.assertEqual(relation.metadata["rawFields"], original["rawFields"])
        user = get_user_model().objects.create_user(username="identity-owner")
        snapshot = batch_herb_component_evidence(query_type="herb", queries=["测试中药"])
        task = save_catalog_analysis(user=user, query_type="herb", queries=["测试中药"], expected_sha256=snapshot["resultSha256"])
        target = next(node for node in task.result["network"]["nodes"] if node["type"] == "target")
        self.assertEqual(target["sourceEntityId"], "T1")
        self.assertEqual(target["sourceReferences"][0]["identifier"], "P04637")
        self.assertEqual(target["organism"], "")
        self.assertTrue(all(item["sourceIdentity"] == original["identity"] for item in task.result["evidenceRecords"]))

    def test_file_change_after_preview_refuses_identity_changes(self):
        self.insert(record())
        run = SyncRun.objects.create(source=self.source)
        preview_sqlite_sync(run)
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE evidence SET extra = ?", (json.dumps(record(uniprot="P14780")),))
        with self.assertRaisesRegex(ValidationError, "变化"):
            apply_sqlite_sync(run)
        self.assertEqual(KnowledgeEntity.objects.count(), 0)

    def test_identity_column_requires_single_target_mode_and_safe_column(self):
        for patch in [{"targetCellMode": "list"}, {"rowMetadataColumn": "extra;DROP TABLE evidence"}]:
            with self.subTest(patch=patch), self.assertRaises(SQLiteSourceError):
                validate_sqlite_source_config({**self.source.configuration, **patch})

    def test_missing_identity_column_fails_before_import(self):
        self.source.configuration["rowMetadataColumn"] = "not_present"
        run = SyncRun.objects.create(source=self.source)
        with self.assertRaisesRegex(ValidationError, "缺少"):
            preview_sqlite_sync(run)

    def test_metadata_validation_rejects_missing_ids_wrong_origin_and_nested_raw_fields(self):
        cases = [record(targetId=""), {**record(), "sourceRow": 3}, {**record(), "rawFields": {"nested": {"x": 1}}},
                 {**record(), "schemaVersion": "unknown"}, {**record(), "workbookSha256": "invalid"}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                read_identity_record(json.dumps(value), 2)
        with self.assertRaises(ValueError):
            read_identity_record("x" * 65537, 2)

    def test_legacy_iterator_contract_is_unchanged_without_metadata_opt_in(self):
        self.insert(record())
        self.assertEqual(list(iter_configured_rows(self.source.configuration)), [("herb", 2, "测试中药", "测试成分", "Tp53")])

    def test_metadata_rejects_nul_nonfinite_values_and_excessive_nesting(self):
        for value in [record(target_id="T\x001"), {**record(), "rawFields": {"x": float("inf")}}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                read_identity_record(json.dumps(value), 2)
        for serialized in ['[' * 2000 + '0' + ']' * 2000,
                           json.dumps({**record(), "rawFields": {"x": "overflow"}}).replace('"overflow"', '1e999')]:
            with self.assertRaises(ValueError):
                read_identity_record(serialized, 2)
        literal = {**record(), "rawFields": {"literal": r"\u0000"}}
        self.assertEqual(read_identity_record(json.dumps(literal), 2), literal)
