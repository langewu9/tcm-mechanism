import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import DataSource, EntityIdentifier, KnowledgeEntity, SourceRelease, SyncRun
from apps.sources.connectors.pubchem import (
    PubChemCatalogError,
    PubChemCatalogSnapshot,
    PubChemCompound,
    fetch_pubchem_compound_catalog,
    validate_pubchem_mappings,
)
from apps.sources.services import _get_pubchem_snapshot, apply_pubchem_sync, preview_pubchem_sync
from apps.sources.tasks import sync_source_run


class PubChemConnectorTests(SimpleTestCase):
    def test_validates_curated_mappings_without_name_based_resolution(self):
        mappings = validate_pubchem_mappings([
            {"stableId": "compound:quercetin", "cid": "5280343"},
            {"stableId": "compound:ferulic-acid", "cid": 445858},
        ])
        self.assertEqual([item.cid for item in mappings], ["445858", "5280343"])
        with self.assertRaisesRegex(PubChemCatalogError, "重复 CID"):
            validate_pubchem_mappings([
                {"stableId": "compound:a", "cid": "5280343"},
                {"stableId": "compound:b", "cid": "5280343"},
            ])
        with self.assertRaisesRegex(PubChemCatalogError, "stableId"):
            validate_pubchem_mappings([{"stableId": "", "cid": "5280343"}])

    def test_fetches_and_checks_requested_cids_and_hashes_properties(self):
        class Response:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def geturl(self):
                return "https://pubchem.ncbi.nlm.nih.gov/rest/pug/test"

            def read(self, limit):
                return self.payload[:limit]

        payload = json.dumps({
            "PropertyTable": {"Properties": [{
                "CID": 5280343,
                "IUPACName": "2-(3,4-dihydroxyphenyl)-3,5,7-trihydroxychromen-4-one",
                "MolecularFormula": "C15H10O7",
                "MolecularWeight": 302.24,
                "CanonicalSMILES": "O=c1c(O)c(-c2ccc(O)c(O)c2)oc2cc(O)cc(O)c12",
                "InChIKey": "REFJWTPEDVJJIY-UHFFFAOYSA-N",
            }]}
        }).encode()
        mappings = [{"stableId": "compound:quercetin", "cid": "5280343"}]
        with patch("apps.sources.connectors.pubchem.urlopen", return_value=Response(payload)):
            snapshot = fetch_pubchem_compound_catalog(mappings)

        self.assertEqual(snapshot.compounds[0].stable_id, "compound:quercetin")
        self.assertEqual(snapshot.compounds[0].molecular_formula, "C15H10O7")
        self.assertEqual(len(snapshot.checksum_sha256), 64)
        self.assertRegex(snapshot.checksum_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(snapshot.release_version, f"sha256-{snapshot.checksum_sha256[:32]}")

    def test_rejects_api_response_for_an_unrequested_cid(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def geturl(self):
                return "https://pubchem.ncbi.nlm.nih.gov/rest/pug/test"

            def read(self, limit):
                return b'{"PropertyTable":{"Properties":[{"CID":1}]}}'

        with patch("apps.sources.connectors.pubchem.urlopen", return_value=Response()):
            with self.assertRaisesRegex(PubChemCatalogError, "CID 与已审核映射不一致"):
                fetch_pubchem_compound_catalog([{"stableId": "compound:quercetin", "cid": "5280343"}])

    def test_stops_when_pubchem_returns_an_async_task(self):
        class Response:
            status = 202

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def geturl(self):
                return "https://pubchem.ncbi.nlm.nih.gov/rest/pug/test"

        with patch("apps.sources.connectors.pubchem.urlopen", return_value=Response()):
            with self.assertRaisesRegex(PubChemCatalogError, "异步任务"):
                fetch_pubchem_compound_catalog([{"stableId": "compound:quercetin", "cid": "5280343"}])


class PubChemSyncTests(TestCase):
    def setUp(self):
        self.source = DataSource.objects.get(slug="pubchem-compounds")
        self.admin = get_user_model().objects.create_superuser(
            username="pubchem-admin",
            email="pubchem-admin@example.test",
            password="test-password-123",
        )
        self.compound = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.COMPOUND,
            stable_id="legacy-compound:quercetin",
            label="槲皮素",
            metadata={"source": "legacy-fixture", "note": "preserve me"},
        )
        self.source.configuration = {
            "connector": "pubchem-compound-catalog",
            "mappings": [{"stableId": self.compound.stable_id, "cid": "5280343"}],
        }
        self.source.save(update_fields=["configuration"])
        self.snapshot = PubChemCatalogSnapshot(
            compounds=(PubChemCompound(
                stable_id=self.compound.stable_id,
                cid="5280343",
                iupac_name="2-(3,4-dihydroxyphenyl)-3,5,7-trihydroxychromen-4-one",
                molecular_formula="C15H10O7",
                molecular_weight="302.24",
                canonical_smiles="O=c1c(O)c(-c2ccc(O)c(O)c2)oc2cc(O)cc(O)c12",
                inchikey="REFJWTPEDVJJIY-UHFFFAOYSA-N",
            ),),
            source_version="snapshot-2026-10-03",
            checksum_sha256="a" * 64,
            page_count=1,
        )

    def make_run(self):
        return SyncRun.objects.create(
            source=self.source,
            requested_by=self.admin,
            preview_summary={"mode": "preview", "connector": "pubchem-compound-catalog"},
        )

    def test_invalid_local_mapping_is_rejected_before_network_access(self):
        self.source.configuration["mappings"] = [{"stableId": "missing-compound", "cid": "5280343"}]
        self.source.save(update_fields=["configuration"])
        with patch("apps.sources.services.fetch_pubchem_compound_catalog") as fetch:
            with self.assertRaisesRegex(Exception, "不存在或已停用"):
                _get_pubchem_snapshot(self.source)
        fetch.assert_not_called()

    def test_pubchem_cid_cannot_be_reassigned_to_a_different_compound(self):
        other = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.COMPOUND,
            stable_id="legacy-compound:another",
            label="另一个成分",
        )
        release = SourceRelease.objects.create(source=self.source, version="legacy-cid-link")
        EntityIdentifier.objects.create(
            entity=other,
            source_release=release,
            namespace="pubchem",
            identifier="5280343",
        )
        with patch("apps.sources.services.fetch_pubchem_compound_catalog") as fetch:
            with self.assertRaisesRegex(Exception, "已关联到其他本地成分"):
                _get_pubchem_snapshot(self.source)
        fetch.assert_not_called()

    def test_preview_is_read_only_and_shows_curated_compound_properties(self):
        run = self.make_run()
        with patch("apps.sources.services._get_pubchem_snapshot", return_value=self.snapshot):
            preview_pubchem_sync(run)

        run.refresh_from_db()
        self.assertEqual(run.preview_summary["wouldCreate"], 1)
        self.assertEqual(run.preview_summary["previewRecords"][0]["compound"], "槲皮素")
        self.assertEqual(run.preview_summary["previewRecords"][0]["molecularFormula"], "C15H10O7")
        self.assertEqual(EntityIdentifier.objects.count(), 0)
        self.assertEqual(self.compound.metadata["note"], "preserve me")

    def test_apply_preserves_source_metadata_and_repeat_preview_is_unchanged(self):
        preview = self.make_run()
        with patch("apps.sources.services._get_pubchem_snapshot", return_value=self.snapshot):
            result = sync_source_run.run(preview.pk)
        preview.refresh_from_db()
        self.assertEqual(result["status"], SyncRun.Status.SUCCEEDED)
        apply_run = SyncRun.objects.create(
            source=self.source,
            release=preview.release,
            cursor=preview.cursor,
            requested_by=self.admin,
            preview_summary={**preview.preview_summary, "mode": "apply", "basedOn": preview.pk},
        )
        with patch("apps.sources.services._get_pubchem_snapshot", return_value=self.snapshot):
            result = sync_source_run.run(apply_run.pk)
        self.assertEqual(result["status"], SyncRun.Status.SUCCEEDED)

        self.compound.refresh_from_db()
        identifier = EntityIdentifier.objects.get(namespace="pubchem", identifier="5280343")
        self.assertEqual(identifier.entity_id, self.compound.pk)
        self.assertEqual(self.compound.metadata["note"], "preserve me")
        self.assertEqual(self.compound.metadata["pubchem"]["molecularFormula"], "C15H10O7")

        repeated = self.make_run()
        with patch("apps.sources.services._get_pubchem_snapshot", return_value=self.snapshot):
            preview_pubchem_sync(repeated)
        self.assertEqual(repeated.preview_summary["wouldCreate"], 0)
        self.assertEqual(repeated.preview_summary["wouldUpdate"], 0)
        self.assertEqual(repeated.preview_summary["unchanged"], 1)

    def test_apply_rejects_a_changed_property_snapshot(self):
        run = self.make_run()
        with patch("apps.sources.services._get_pubchem_snapshot", return_value=self.snapshot):
            preview_pubchem_sync(run)
        changed = PubChemCatalogSnapshot(
            compounds=(PubChemCompound(
                stable_id=self.compound.stable_id,
                cid="5280343",
                iupac_name="changed",
                molecular_formula="C15H10O7",
                molecular_weight="302.24",
                canonical_smiles="",
                inchikey="REFJWTPEDVJJIY-UHFFFAOYSA-N",
            ),),
            source_version="snapshot-2026-10-03",
            checksum_sha256="b" * 64,
            page_count=1,
        )
        with patch("apps.sources.services._get_pubchem_snapshot", return_value=changed):
            with self.assertRaisesRegex(Exception, "预览后已变化"):
                apply_pubchem_sync(run)
        self.assertEqual(EntityIdentifier.objects.count(), 0)


class PubChemSyncApiTests(APITestCase):
    def setUp(self):
        self.source = DataSource.objects.get(slug="pubchem-compounds")
        user_model = get_user_model()
        self.researcher = user_model.objects.create_user(
            username="pubchem-researcher", password="test-password-123"
        )
        self.admin = user_model.objects.create_superuser(
            username="pubchem-platform-admin",
            email="pubchem-admin@example.test",
            password="test-password-123",
        )

    def test_only_platform_admin_can_start_a_pubchem_preview(self):
        url = reverse("sync-source-preview", args=[self.source.pk])
        self.client.force_authenticate(self.researcher)
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 403)

        self.client.force_authenticate(self.admin)
        with patch("apps.sources.tasks.sync_source_run.delay") as enqueue:
            response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, 202)
        run = SyncRun.objects.get(pk=response.data["run"]["id"])
        self.assertEqual(run.requested_by, self.admin)
        self.assertEqual(run.preview_summary["connector"], "pubchem-compound-catalog")
        enqueue.assert_called_once_with(run.pk)

        # The mocked worker must finish before another same-source task may start.
        run.status = SyncRun.Status.SUCCEEDED
        run.save(update_fields=["status"])

        release = SourceRelease.objects.create(
            source=self.source,
            version="sha256-smoke-preview",
            checksum_sha256="a" * 64,
        )
        preview = SyncRun.objects.create(
            source=self.source,
            release=release,
            cursor=release.checksum_sha256,
            status=SyncRun.Status.SUCCEEDED,
            preview_summary={"mode": "preview", "connector": "pubchem-compound-catalog"},
        )
        with patch("apps.sources.tasks.sync_source_run.delay") as enqueue:
            response = self.client.post(reverse("sync-run-apply", args=[preview.pk]), {}, format="json")
        self.assertEqual(response.status_code, 202)
        apply_run = SyncRun.objects.get(pk=response.data["run"]["id"])
        self.assertEqual(apply_run.preview_summary["basedOn"], preview.pk)
        enqueue.assert_called_once_with(apply_run.pk)
