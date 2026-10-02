import hashlib
import sqlite3
import tempfile
from unittest.mock import patch
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease, SyncRun
from apps.sources.connectors.reactome import (
    ReactomeCatalogError,
    ReactomeCatalogSnapshot,
    ReactomePathway,
    parse_human_pathway_catalog,
)
from apps.sources.tasks import sync_source_run


class ReactomeCatalogParserTests(TestCase):
    def test_keeps_unique_human_pathways_and_ignores_other_species(self):
        data = (
            "R-HSA-2\tSecond pathway\tHomo sapiens\n"
            "R-HSA-1\tFirst pathway\tHomo sapiens\n"
            "R-HSA-1\tUpdated first pathway\tHomo sapiens\n"
            "R-MMU-1\tMouse pathway\tMus musculus\n"
            "not-a-pathway\tInvalid\tHomo sapiens\n"
        ).encode()

        pathways = parse_human_pathway_catalog(data)

        self.assertEqual([item.stable_id for item in pathways], ["R-HSA-1", "R-HSA-2"])
        self.assertEqual(pathways[0].name, "Updated first pathway")

    def test_empty_or_invalid_catalog_is_rejected(self):
        with self.assertRaisesRegex(ReactomeCatalogError, "未找到有效的人类通路"):
            parse_human_pathway_catalog(b"R-MMU-1\tMouse\tMus musculus\n")
        with self.assertRaisesRegex(ReactomeCatalogError, "UTF-8"):
            parse_human_pathway_catalog(b"\xff\xfe\xff")


class ReactomeSyncTaskTests(TestCase):
    def setUp(self):
        self.source = DataSource.objects.get(slug="reactome")
        self.admin = get_user_model().objects.create_superuser(
            username="sync-admin", email="sync-admin@example.test", password="test-password-123"
        )

    def snapshot(self, *pathways):
        checksum = hashlib.sha256("|".join(item.stable_id + item.name for item in pathways).encode()).hexdigest()
        return ReactomeCatalogSnapshot(tuple(pathways), "97", checksum)

    def test_preview_creates_version_audit_but_does_not_change_catalog_entities(self):
        existing_release = SourceRelease.objects.create(source=self.source, version="old")
        KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.PATHWAY,
            stable_id="R-HSA-1",
            label="Existing pathway",
            organism="Homo sapiens",
            source_release=existing_release,
        )
        run = SyncRun.objects.create(
            source=self.source,
            requested_by=self.admin,
            preview_summary={"mode": "preview"},
        )
        catalog = self.snapshot(
            ReactomePathway("R-HSA-1", "Renamed pathway"),
            ReactomePathway("R-HSA-2", "New pathway"),
        )

        with patch("apps.sources.services._get_snapshot", return_value=catalog):
            outcome = sync_source_run.run(run.pk)

        run.refresh_from_db()
        self.assertEqual(outcome["status"], SyncRun.Status.SUCCEEDED)
        self.assertEqual(run.requested_by, self.admin)
        self.assertEqual(run.records_seen, 2)
        self.assertEqual(run.preview_summary["wouldCreate"], 1)
        self.assertEqual(run.preview_summary["wouldUpdate"], 1)
        self.assertEqual(run.release.checksum_sha256, catalog.checksum_sha256)
        self.assertEqual(KnowledgeEntity.objects.count(), 1)
        self.assertEqual(KnowledgeEntity.objects.get().label, "Existing pathway")
        self.assertIsNone(self.source.last_success_at)

    def test_sync_audit_prevents_deleting_the_recorded_administrator(self):
        SyncRun.objects.create(source=self.source, requested_by=self.admin)

        with self.assertRaises(ProtectedError):
            self.admin.delete()

    def test_apply_is_idempotent_and_soft_retires_removed_source_rows(self):
        previous_release = SourceRelease.objects.create(source=self.source, version="previous")
        keep = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.PATHWAY,
            stable_id="R-HSA-1",
            label="Old name",
            organism="Homo sapiens",
            source_release=previous_release,
        )
        retire = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.PATHWAY,
            stable_id="R-HSA-9",
            label="Removed pathway",
            organism="Homo sapiens",
            source_release=previous_release,
        )
        catalog = self.snapshot(ReactomePathway("R-HSA-1", "Current name"))
        release = SourceRelease.objects.create(
            source=self.source,
            version=catalog.release_version,
            checksum_sha256=catalog.checksum_sha256,
        )
        run = SyncRun.objects.create(
            source=self.source,
            release=release,
            cursor=catalog.checksum_sha256,
            requested_by=self.admin,
            preview_summary={"mode": "apply", "basedOn": 10},
        )

        with patch("apps.sources.services._get_snapshot", return_value=catalog):
            sync_source_run.run(run.pk)

        run.refresh_from_db()
        keep.refresh_from_db()
        retire.refresh_from_db()
        self.assertEqual(run.status, SyncRun.Status.SUCCEEDED)
        self.assertEqual(run.records_updated, 1)
        self.assertEqual(run.records_retired, 1)
        self.assertEqual(keep.label, "Current name")
        self.assertEqual(keep.source_release, release)
        self.assertTrue(keep.is_active)
        self.assertFalse(retire.is_active)
        self.assertEqual(KnowledgeEntity.objects.count(), 2)
        self.assertIsNotNone(DataSource.objects.get(pk=self.source.pk).last_success_at)

        second_run = SyncRun.objects.create(
            source=self.source,
            release=release,
            cursor=catalog.checksum_sha256,
            preview_summary={"mode": "apply", "basedOn": 11},
        )
        with patch("apps.sources.services._get_snapshot", return_value=catalog):
            sync_source_run.run(second_run.pk)
        self.assertEqual(KnowledgeEntity.objects.count(), 2)
        self.assertEqual(KnowledgeEntity.objects.filter(is_active=True).count(), 1)

    def test_apply_refuses_changed_snapshot_without_modifying_catalog(self):
        original = self.snapshot(ReactomePathway("R-HSA-1", "Preview name"))
        changed = self.snapshot(ReactomePathway("R-HSA-1", "Changed after preview"))
        release = SourceRelease.objects.create(
            source=self.source,
            version=original.release_version,
            checksum_sha256=original.checksum_sha256,
        )
        run = SyncRun.objects.create(
            source=self.source,
            release=release,
            cursor=original.checksum_sha256,
            preview_summary={"mode": "apply", "basedOn": 12},
        )

        with patch("apps.sources.services._get_snapshot", return_value=changed):
            sync_source_run.run(run.pk)

        run.refresh_from_db()
        self.assertEqual(run.status, SyncRun.Status.FAILED)
        self.assertIn("源文件在预览后已变化", run.error_summary)
        self.assertEqual(KnowledgeEntity.objects.count(), 0)


class ReactomeSyncApiTests(APITestCase):
    def setUp(self):
        self.source = DataSource.objects.get(slug="reactome")
        user_model = get_user_model()
        self.researcher = user_model.objects.create_user(username="researcher", password="test-password-123")
        self.admin = user_model.objects.create_superuser(
            username="platform-admin", email="admin@example.test", password="test-password-123"
        )

    def test_only_superuser_can_list_sources_and_start_a_preview(self):
        list_url = reverse("sync-source-list")
        preview_url = reverse("sync-source-preview", args=[self.source.pk])
        self.client.force_authenticate(self.researcher)
        self.assertEqual(self.client.get(list_url).status_code, 403)
        self.assertEqual(self.client.post(preview_url, {}, format="json").status_code, 403)

        self.client.force_authenticate(self.admin)
        with patch("apps.sources.tasks.sync_source_run.delay") as enqueue:
            response = self.client.post(preview_url, {}, format="json")

        self.assertEqual(response.status_code, 202)
        run = SyncRun.objects.get(pk=response.data["run"]["id"])
        self.assertEqual(run.requested_by, self.admin)
        self.assertEqual(run.preview_summary["mode"], "preview")
        enqueue.assert_called_once_with(run.pk)

    def test_queue_failure_is_recorded_and_returns_standard_service_error(self):
        self.client.force_authenticate(self.admin)
        with patch("apps.sources.tasks.sync_source_run.delay", side_effect=OSError("Redis unavailable")):
            response = self.client.post(
                reverse("sync-source-preview", args=[self.source.pk]), {}, format="json"
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["error"]["code"], "SERVICE_UNAVAILABLE")
        run = SyncRun.objects.latest("created_at")
        self.assertEqual(run.status, SyncRun.Status.FAILED)
        self.assertIn("worker", run.error_summary)

    def test_only_a_successful_preview_can_be_applied_and_apply_is_audited(self):
        self.client.force_authenticate(self.admin)
        catalog = ReactomeCatalogSnapshot(
            (ReactomePathway("R-HSA-1", "Pathway"),), "97", "b" * 64
        )
        release = SourceRelease.objects.create(
            source=self.source,
            version=catalog.release_version,
            checksum_sha256=catalog.checksum_sha256,
        )
        preview = SyncRun.objects.create(
            source=self.source,
            release=release,
            cursor=catalog.checksum_sha256,
            status=SyncRun.Status.SUCCEEDED,
            preview_summary={"mode": "preview"},
        )
        with patch("apps.sources.tasks.sync_source_run.delay") as enqueue:
            response = self.client.post(reverse("sync-run-apply", args=[preview.pk]), {}, format="json")

        self.assertEqual(response.status_code, 202)
        apply_run = SyncRun.objects.get(pk=response.data["run"]["id"])
        self.assertEqual(apply_run.preview_summary["basedOn"], preview.pk)
        self.assertEqual(apply_run.requested_by, self.admin)
        enqueue.assert_called_once_with(apply_run.pk)

        duplicate = self.client.post(reverse("sync-run-apply", args=[preview.pk]), {}, format="json")
        self.assertEqual(duplicate.status_code, 400)

    def test_retired_entities_and_relations_are_hidden_from_active_catalog(self):
        release = SourceRelease.objects.create(source=self.source, version="97")
        active_gene = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.GENE,
            stable_id="TP53",
            label="TP53",
        )
        retired_pathway = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.PATHWAY,
            stable_id="R-HSA-1",
            label="Removed pathway",
            source_release=release,
            is_active=False,
        )
        EvidenceRelation.objects.create(
            source_release=release,
            source_record_id="TP53-R-HSA-1",
            subject=active_gene,
            object=retired_pathway,
            relation_type="participates_in",
            evidence_type="reactome_pathway_membership",
        )
        self.client.force_authenticate(self.admin)

        entity_response = self.client.get(reverse("entity-list"))
        evidence_response = self.client.get(reverse("evidence-list"))

        self.assertEqual(entity_response.status_code, 200)
        self.assertEqual([item["stable_id"] for item in entity_response.data["results"]], ["TP53"])
        self.assertEqual(evidence_response.status_code, 200)
        self.assertEqual(evidence_response.data["count"], 0)


class SQLiteSourceSyncTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_superuser(
            username="sqlite-admin", email="sqlite-admin@example.test", password="test-password-123"
        )
        self.client.force_authenticate(self.admin)

    def create_legacy_file(self, root: str) -> Path:
        path = Path(root) / "legacy.sqlite3"
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE herb_component_target "
                "(herb TEXT, component TEXT, target TEXT)"
            )
            connection.executemany(
                "INSERT INTO herb_component_target VALUES (?, ?, ?)",
                [
                    ("黄芩", "黄芩苷", "TP53;IL6; IL6"),
                    ("黄芩", "黄芩素", "IL6"),
                ],
            )
        return path

    def source_payload(self):
        return {
            "name": "Legacy herb-target data",
            "description": "Synthetic migration fixture",
            "databaseFile": "legacy.sqlite3",
            "table": "herb_component_target",
            "herbColumn": "herb",
            "compoundColumn": "component",
            "targetColumn": "target",
        }

    def test_create_test_preview_and_apply_sqlite_source_without_exposing_server_path(self):
        with tempfile.TemporaryDirectory() as root, override_settings(SQLITE_SOURCE_ROOT=root):
            path = self.create_legacy_file(root)
            response = self.client.post(reverse("sync-source-list"), self.source_payload(), format="json")
            self.assertEqual(response.status_code, 201)
            self.assertNotIn("configuration", response.data)
            self.assertNotIn(str(path), str(response.data))
            source_id = response.data["id"]

            test_response = self.client.post(reverse("sync-source-test", args=[source_id]), {}, format="json")
            self.assertEqual(test_response.status_code, 200)
            self.assertEqual(test_response.data["rowCount"], 2)
            self.assertEqual(test_response.data["mapping"]["table"], "herb_component_target")
            self.assertNotIn(str(path.parent), str(test_response.data))

            with patch("apps.sources.tasks.sync_source_run.delay"):
                preview_response = self.client.post(
                    reverse("sync-source-preview", args=[source_id]), {}, format="json"
                )
            self.assertEqual(preview_response.status_code, 202)
            preview_id = preview_response.data["run"]["id"]
            sync_source_run.run(preview_id)
            preview = SyncRun.objects.get(pk=preview_id)
            self.assertEqual(preview.status, SyncRun.Status.SUCCEEDED)
            self.assertEqual(preview.preview_summary["uniqueHerbs"], 1)
            self.assertEqual(preview.preview_summary["uniqueCompounds"], 2)
            self.assertEqual(preview.preview_summary["uniqueTargets"], 2)
            self.assertEqual(preview.preview_summary["relationships"], 5)
            self.assertEqual(KnowledgeEntity.objects.count(), 0)

            with patch("apps.sources.tasks.sync_source_run.delay"):
                apply_response = self.client.post(reverse("sync-run-apply", args=[preview_id]), {}, format="json")
            self.assertEqual(apply_response.status_code, 202)
            apply_id = apply_response.data["run"]["id"]
            sync_source_run.run(apply_id)
            apply_run = SyncRun.objects.get(pk=apply_id)

            self.assertEqual(apply_run.status, SyncRun.Status.SUCCEEDED)
            self.assertEqual(apply_run.records_created, 5)
            self.assertEqual(apply_run.preview_summary["relationshipsCreated"], 5)
            self.assertEqual(KnowledgeEntity.objects.filter(is_active=True).count(), 5)
            self.assertEqual(EvidenceRelation.objects.filter(is_active=True).count(), 5)
            self.assertEqual(
                KnowledgeEntity.objects.get(entity_type=KnowledgeEntity.EntityType.PROTEIN, label="TP53")
                .metadata["symbol"],
                "TP53",
            )

            with patch("apps.sources.tasks.sync_source_run.delay"):
                repeat_preview_response = self.client.post(
                    reverse("sync-source-preview", args=[source_id]), {}, format="json"
                )
                repeat_preview_id = repeat_preview_response.data["run"]["id"]
                sync_source_run.run(repeat_preview_id)
                repeat_preview = SyncRun.objects.get(pk=repeat_preview_id)
                repeat_apply_response = self.client.post(
                    reverse("sync-run-apply", args=[repeat_preview_id]), {}, format="json"
                )
            repeat_apply_id = repeat_apply_response.data["run"]["id"]
            sync_source_run.run(repeat_apply_id)
            repeat_apply = SyncRun.objects.get(pk=repeat_apply_id)
            self.assertEqual(repeat_preview.preview_summary["wouldCreate"], 0)
            self.assertEqual(repeat_preview.preview_summary["wouldUpdate"], 0)
            self.assertEqual(repeat_apply.records_created, 0)
            self.assertEqual(repeat_apply.records_updated, 0)
            self.assertEqual(repeat_apply.preview_summary["entitiesUnchanged"], 5)
            self.assertEqual(KnowledgeEntity.objects.filter(is_active=True).count(), 5)
            self.assertEqual(EvidenceRelation.objects.filter(is_active=True).count(), 5)

    def test_database_path_and_sql_identifiers_are_confined_and_validated(self):
        payload = self.source_payload()
        payload["databaseFile"] = "../outside.sqlite3"
        response = self.client.post(reverse("sync-source-list"), payload, format="json")
        self.assertEqual(response.status_code, 400)

        payload = self.source_payload()
        payload["table"] = "herb_component_target; DROP TABLE users"
        response = self.client.post(reverse("sync-source-list"), payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_source_file_change_after_preview_prevents_import(self):
        with tempfile.TemporaryDirectory() as root, override_settings(SQLITE_SOURCE_ROOT=root):
            self.create_legacy_file(root)
            create_response = self.client.post(reverse("sync-source-list"), self.source_payload(), format="json")
            source_id = create_response.data["id"]
            with patch("apps.sources.tasks.sync_source_run.delay"):
                preview_response = self.client.post(
                    reverse("sync-source-preview", args=[source_id]), {}, format="json"
                )
            preview_id = preview_response.data["run"]["id"]
            sync_source_run.run(preview_id)
            preview = SyncRun.objects.get(pk=preview_id)
            with sqlite3.connect(Path(root) / "legacy.sqlite3") as connection:
                connection.execute("INSERT INTO herb_component_target VALUES (?, ?, ?)", ("丹参", "丹参酮", "AKT1"))

            with patch("apps.sources.tasks.sync_source_run.delay"):
                apply_response = self.client.post(reverse("sync-run-apply", args=[preview_id]), {}, format="json")
            apply_id = apply_response.data["run"]["id"]
            sync_source_run.run(apply_id)
            apply_run = SyncRun.objects.get(pk=apply_id)

            self.assertEqual(apply_run.status, SyncRun.Status.FAILED)
            self.assertIn("文件在预览后已变化", apply_run.error_summary)
            self.assertEqual(KnowledgeEntity.objects.count(), 0)

    def test_mapping_change_after_preview_prevents_import(self):
        with tempfile.TemporaryDirectory() as root, override_settings(SQLITE_SOURCE_ROOT=root):
            self.create_legacy_file(root)
            create_response = self.client.post(reverse("sync-source-list"), self.source_payload(), format="json")
            source_id = create_response.data["id"]
            with patch("apps.sources.tasks.sync_source_run.delay"):
                preview_response = self.client.post(
                    reverse("sync-source-preview", args=[source_id]), {}, format="json"
                )
            preview_id = preview_response.data["run"]["id"]
            sync_source_run.run(preview_id)
            preview = SyncRun.objects.get(pk=preview_id)
            source = DataSource.objects.get(pk=source_id)
            source.configuration["targetColumn"] = "component"
            source.save(update_fields=["configuration"])

            with patch("apps.sources.tasks.sync_source_run.delay"):
                apply_response = self.client.post(reverse("sync-run-apply", args=[preview_id]), {}, format="json")
            apply_id = apply_response.data["run"]["id"]
            sync_source_run.run(apply_id)
            apply_run = SyncRun.objects.get(pk=apply_id)

            self.assertEqual(apply_run.status, SyncRun.Status.FAILED)
            self.assertIn("列映射在预览后已变化", apply_run.error_summary)
            self.assertEqual(KnowledgeEntity.objects.count(), 0)

    def test_empty_mapped_table_does_not_create_a_preview_or_retire_existing_entities(self):
        with tempfile.TemporaryDirectory() as root, override_settings(SQLITE_SOURCE_ROOT=root):
            path = Path(root) / "legacy.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE herb_component_target (herb TEXT, component TEXT, target TEXT)")
                connection.execute("INSERT INTO herb_component_target VALUES ('', '', '')")
            create_response = self.client.post(reverse("sync-source-list"), self.source_payload(), format="json")
            source = DataSource.objects.get(pk=create_response.data["id"])
            release = SourceRelease.objects.create(source=source, version="prior")
            existing = KnowledgeEntity.objects.create(
                entity_type=KnowledgeEntity.EntityType.HERB,
                stable_id="sqlite:old-source:herb:old",
                label="已有中药",
                source_release=release,
            )
            with patch("apps.sources.tasks.sync_source_run.delay"):
                response = self.client.post(
                    reverse("sync-source-preview", args=[source.pk]), {}, format="json"
                )
            run_id = response.data["run"]["id"]
            sync_source_run.run(run_id)
            run = SyncRun.objects.get(pk=run_id)
            existing.refresh_from_db()

            self.assertEqual(run.status, SyncRun.Status.FAILED)
            self.assertIn("没有有效的中药—成分—靶点关系", run.error_summary)
            self.assertTrue(existing.is_active)
