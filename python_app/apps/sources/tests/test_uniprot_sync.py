import hashlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import DataSource, EntityIdentifier, KnowledgeEntity, SourceRelease, SyncRun
from apps.proteomics.services import _entity_aliases
from apps.sources.connectors.uniprot import (
    UniProtCatalogError,
    UniProtCatalogSnapshot,
    UniProtProtein,
    fetch_uniprot_human_catalog,
    parse_uniprot_human_catalog,
)
from apps.sources.services import apply_uniprot_sync, preview_uniprot_sync
from rest_framework.exceptions import ValidationError


HEADER = "Entry\tProtein names\tGene Names (primary)\tGene Names\tOrganism\n"


class UniProtCatalogParserTests(SimpleTestCase):
    def test_parses_releases_deduplicates_and_keeps_gene_aliases(self):
        tsv = (
            HEADER
            + "P04637\tCellular tumor antigen p53\tTP53\tTP53 P53\tHomo sapiens (Human)\n"
            + "P04637\tUpdated name\tTP53\tTP53 P53\tHomo sapiens (Human)\n"
            + "Q9H0H5\tProtein name\tEGFR\tEGFR ERBB1\tHomo sapiens (Human)\n"
        ).encode()
        proteins = parse_uniprot_human_catalog(tsv, source_version="2026_03")

        self.assertEqual([protein.accession for protein in proteins], ["P04637", "Q9H0H5"])
        self.assertEqual(proteins[0].protein_name, "Updated name")
        self.assertEqual(proteins[0].gene_names, ("TP53", "P53"))

    def test_rejects_changed_columns_invalid_accession_and_wrong_species(self):
        with self.assertRaisesRegex(UniProtCatalogError, "列结构发生变化"):
            parse_uniprot_human_catalog(b"unexpected\tcolumns\n", source_version="2026_03")
        with self.assertRaisesRegex(UniProtCatalogError, "无效的 accession"):
            parse_uniprot_human_catalog(
                (HEADER + "BAD_ID\tProtein\tTP53\tTP53\tHomo sapiens (Human)\n").encode(),
                source_version="2026_03",
            )
        with self.assertRaisesRegex(UniProtCatalogError, "非人类"):
            parse_uniprot_human_catalog(
                (HEADER + "P04637\tProtein\tTP53\tTP53\tMus musculus (Mouse)\n").encode(),
                source_version="2026_03",
            )
        with self.assertRaisesRegex(UniProtCatalogError, "非人类"):
            parse_uniprot_human_catalog(
                (HEADER + "P04637\tProtein\tTP53\tTP53\tHomo sapiens unexpected species\n").encode(),
                source_version="2026_03",
            )

    def test_fetch_follows_release_pagination_and_verifies_the_total(self):
        first_url = "https://rest.uniprot.org/uniprotkb/search?first"
        second_url = "https://rest.uniprot.org/uniprotkb/search?cursor=page2"
        page_one = (
            HEADER + "P04637\tCellular tumor antigen p53\tTP53\tTP53 P53\tHomo sapiens (Human)\n"
        ).encode()
        page_two = (
            HEADER + "Q9H0H5\tProtein name\tEGFR\tEGFR ERBB1\tHomo sapiens (Human)\n"
        ).encode()

        class Response:
            status = 200

            def __init__(self, payload, headers):
                self.payload = payload
                self.headers = headers

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return self.payload[:limit]

        responses = iter([
            Response(page_one, {
                "X-Total-Results": "2",
                "X-UniProt-Release": "2026_03",
                "X-UniProt-Release-Date": "2026-03-18",
                "Link": f'<{second_url}>; rel="next"',
            }),
            Response(page_two, {
                "X-Total-Results": "2",
                "X-UniProt-Release": "2026_03",
            }),
        ])
        with patch("apps.sources.connectors.uniprot.urlopen", side_effect=lambda *a, **k: next(responses)):
            snapshot = fetch_uniprot_human_catalog()

        self.assertEqual(snapshot.source_version, "2026_03")
        self.assertEqual(snapshot.page_count, 2)
        self.assertEqual(snapshot.total_results, 2)
        self.assertEqual([protein.accession for protein in snapshot.proteins], ["P04637", "Q9H0H5"])
        self.assertEqual(len(snapshot.checksum_sha256), 64)


class UniProtSyncTests(TestCase):
    def setUp(self):
        self.source = DataSource.objects.get(slug="uniprot-human")
        self.local_source = DataSource.objects.create(
            slug="legacy-fixture",
            name="legacy fixture",
            access_mode=DataSource.AccessMode.MANUAL,
        )
        self.admin = get_user_model().objects.create_superuser(
            username="uniprot-admin",
            email="uniprot-admin@example.test",
            password="test-password-123",
        )
        self.legacy_release = SourceRelease.objects.create(source=self.local_source, version="fixture-v1")
        self.local_target = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.PROTEIN,
            stable_id="legacy-target:TP53",
            label="TP53",
            organism="Homo sapiens",
            source_release=self.legacy_release,
            metadata={"source": self.local_source.slug, "symbol": "TP53", "identifierStatus": "verified"},
        )
        self.snapshot = self.build_snapshot(
            UniProtProtein("P04637", "Cellular tumor antigen p53", "TP53", ("TP53", "P53")),
            UniProtProtein("Q9H0H5", "Protein tyrosine kinase", "EGFR", ("EGFR", "ERBB1")),
        )

    def build_snapshot(self, *proteins, version="2026_03"):
        payload = "|".join(
            f"{protein.accession}:{protein.protein_name}:{protein.primary_gene}:{','.join(protein.gene_names)}"
            for protein in proteins
        ).encode()
        checksum = hashlib.sha256(payload).hexdigest()
        return UniProtCatalogSnapshot(tuple(proteins), version, "2026-03-18", checksum, len(proteins), 1)

    def make_run(self):
        return SyncRun.objects.create(
            source=self.source,
            requested_by=self.admin,
            preview_summary={"mode": "preview", "connector": "uniprot-human-catalog"},
        )

    def test_preview_is_read_only_and_records_counts_release_and_checksum(self):
        run = self.make_run()
        with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
            preview_uniprot_sync(run)

        run.refresh_from_db()
        self.assertEqual(run.records_seen, 2)
        self.assertEqual(run.preview_summary["wouldCreate"], 2)
        self.assertEqual(run.preview_summary["geneSymbolsMappedToExistingTargets"], 1)
        self.assertEqual(run.preview_summary["releaseVersion"], self.snapshot.release_version)
        self.assertEqual(run.release.checksum_sha256, self.snapshot.checksum_sha256)
        self.assertEqual(KnowledgeEntity.objects.count(), 1)
        self.assertEqual(EntityIdentifier.objects.count(), 0)

    def test_apply_maps_accessions_to_existing_targets_and_is_idempotent(self):
        run = self.make_run()
        with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
            preview_uniprot_sync(run)
            apply_uniprot_sync(run)

        run.refresh_from_db()
        accession = EntityIdentifier.objects.get(namespace="uniprot", identifier="P04637")
        gene_alias = EntityIdentifier.objects.get(namespace="uniprot-gene-name", identifier="P53")
        egfr = EntityIdentifier.objects.get(namespace="uniprot", identifier="Q9H0H5")
        self.assertEqual(accession.entity_id, self.local_target.pk)
        self.assertEqual(gene_alias.entity_id, self.local_target.pk)
        self.assertEqual(egfr.entity.entity_type, KnowledgeEntity.EntityType.GENE)
        self.assertEqual(egfr.entity.stable_id, "uniprot-gene:EGFR")
        self.assertEqual(run.records_created, 2)
        self.assertEqual(run.status, SyncRun.Status.PENDING)
        self.assertIn("UNIPROT-GENE:EGFR", _entity_aliases(egfr.entity))
        self.assertIn("ERBB1", _entity_aliases(egfr.entity))

        repeat_preview = self.make_run()
        with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
            preview_uniprot_sync(repeat_preview)
            second = SyncRun.objects.create(
                source=self.source, release=repeat_preview.release, cursor=repeat_preview.cursor,
                preview_summary={**repeat_preview.preview_summary, "mode": "apply", "basedOn": repeat_preview.pk},
            )
            apply_uniprot_sync(second)

        self.assertEqual(repeat_preview.preview_summary["wouldCreate"], 0)
        self.assertEqual(repeat_preview.preview_summary["wouldUpdate"], 0)
        self.assertEqual(repeat_preview.preview_summary["unchanged"], 2)
        self.assertEqual(EntityIdentifier.objects.filter(namespace="uniprot", is_active=True).count(), 2)
        self.assertEqual(KnowledgeEntity.objects.filter(stable_id="uniprot-gene:EGFR").count(), 1)
        self.assertEqual(EntityIdentifier.objects.filter(namespace="uniprot-gene-name", identifier="ERBB1").count(), 1)

    def test_apply_refuses_a_changed_release_snapshot(self):
        run = self.make_run()
        with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
            preview_uniprot_sync(run)
        changed = self.build_snapshot(
            UniProtProtein("P04637", "Changed name", "TP53", ("TP53", "P53")),
            version="2026_03",
        )
        with patch("apps.sources.services._get_uniprot_snapshot", return_value=changed):
            with self.assertRaisesRegex(Exception, "目录在预览后已变化"):
                apply_uniprot_sync(run)
        self.assertEqual(EntityIdentifier.objects.count(), 0)

    def preview_and_apply(self):
        run = self.make_run()
        with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
            preview_uniprot_sync(run)
            apply_uniprot_sync(run)
        return run

    def assert_separate_catalogue_identity(self):
        row = EntityIdentifier.objects.get(namespace="uniprot", identifier="P04637")
        self.assertNotEqual(row.entity_id, self.local_target.pk)
        self.assertEqual(row.entity.organism, "Homo sapiens")
        self.assertEqual(row.entity.source_release.source_id, self.source.pk)

    def test_unknown_species_is_counted_and_kept_separate(self):
        self.local_target.organism = ""
        self.local_target.save()
        run = self.preview_and_apply()
        self.assertEqual(run.preview_summary["unknownSpeciesLocalTargets"], 1)
        self.assertEqual(run.preview_summary["geneSymbolsMappedToExistingTargets"], 0)
        self.assert_separate_catalogue_identity()

    def test_mouse_symbol_cannot_receive_a_human_accession(self):
        self.local_target.organism = "Mus musculus"
        self.local_target.save()
        run = self.preview_and_apply()
        self.assertEqual(run.preview_summary["otherSpeciesLocalTargets"], 1)
        self.assert_separate_catalogue_identity()

    def test_unverified_historical_symbol_is_not_promoted_by_same_name(self):
        for status in ["name_only", "unverified_symbol"]:
            with self.subTest(status=status):
                self.local_target.metadata["identifierStatus"] = status
                self.local_target.save()
                run = self.make_run()
                with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
                    preview_uniprot_sync(run)
                self.assertEqual(run.preview_summary["geneSymbolsMappedToExistingTargets"], 0)
                self.assertEqual(run.preview_summary["unverifiedLocalTargets"], 1)
        with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
            apply_uniprot_sync(run)
        self.assert_separate_catalogue_identity()

    def test_disabled_source_target_is_not_reused(self):
        self.local_source.enabled = False
        self.local_source.save()
        run = self.preview_and_apply()
        self.assertEqual(run.preview_summary["geneSymbolsMappedToExistingTargets"], 0)
        self.assert_separate_catalogue_identity()

    def test_ambiguous_human_targets_are_kept_separate(self):
        KnowledgeEntity.objects.create(entity_type="protein", stable_id="other:TP53", label="Another target",
            organism="Homo sapiens", source_release=self.legacy_release, metadata={"symbol": "TP53"})
        run = self.preview_and_apply()
        self.assertEqual(run.preview_summary["ambiguousLocalGeneSymbols"], 1)
        self.assert_separate_catalogue_identity()

    def test_preview_and_apply_normalize_the_same_human_symbol(self):
        self.local_target.metadata["symbol"] = "  tp53  "
        self.local_target.save()
        run = self.preview_and_apply()
        self.assertEqual(run.preview_summary["geneSymbolsMappedToExistingTargets"], 1)
        self.assertEqual(EntityIdentifier.objects.get(namespace="uniprot", identifier="P04637").entity_id,
                         self.local_target.pk)

    def test_existing_accession_ownership_wins_over_a_new_symbol_candidate(self):
        self.local_target.organism = ""
        self.local_target.save()
        self.preview_and_apply()
        accession = EntityIdentifier.objects.get(namespace="uniprot", identifier="P04637")
        owner_id = accession.entity_id
        self.local_target.organism = "Homo sapiens"
        self.local_target.save()
        run = self.preview_and_apply()
        accession.refresh_from_db()
        self.assertEqual(accession.entity_id, owner_id)
        self.assertGreater(run.preview_summary["preservedAccessionMappings"], 0)

    def test_invalid_existing_accession_owner_blocks_apply_without_mutation(self):
        self.local_target.organism = "Mus musculus"
        self.local_target.save()
        accession = EntityIdentifier.objects.create(entity=self.local_target, source_release=self.legacy_release,
                                                   namespace="uniprot", identifier="P04637")
        run = self.make_run()
        with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
            preview_uniprot_sync(run)
            self.assertEqual(run.preview_summary["identifierConflicts"], 1)
            with self.assertRaisesRegex(ValidationError, "归属冲突"):
                apply_uniprot_sync(run)
        accession.refresh_from_db()
        self.assertEqual(accession.entity_id, self.local_target.pk)
        self.assertEqual(accession.source_release_id, self.legacy_release.pk)
        self.assertTrue(accession.is_active)
        self.assertEqual(KnowledgeEntity.objects.count(), 1)

    def test_changed_local_identity_after_preview_requires_a_new_preview(self):
        for change in ["species", "source_enabled", "symbol", "new_ambiguity"]:
            with self.subTest(change=change):
                run = self.make_run()
                with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
                    preview_uniprot_sync(run)
                    if change == "species":
                        self.local_target.organism = "Mus musculus"
                        self.local_target.save()
                    elif change == "source_enabled":
                        self.local_source.enabled = False
                        self.local_source.save()
                    elif change == "symbol":
                        self.local_target.metadata["symbol"] = "OTHER"
                        self.local_target.save()
                    else:
                        extra = KnowledgeEntity.objects.create(entity_type="protein", stable_id="extra:TP53",
                            label="TP53", organism="Homo sapiens", metadata={"symbol": "TP53"})
                    with self.assertRaisesRegex(ValidationError, "重新预览"):
                        apply_uniprot_sync(run)
                self.assertEqual(EntityIdentifier.objects.count(), 0)
                self.local_target.organism = "Homo sapiens"
                self.local_target.metadata["symbol"] = "TP53"
                self.local_target.save()
                self.local_source.enabled = True
                self.local_source.save()
                if change == "new_ambiguity":
                    extra.delete()

    def test_legacy_preview_without_identity_proof_requires_repreview(self):
        run = self.make_run()
        with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
            preview_uniprot_sync(run)
            run.preview_summary.pop("identityPlanSha256", None)
            with self.assertRaisesRegex(ValidationError, "重新预览"):
                apply_uniprot_sync(run)
        self.assertEqual(EntityIdentifier.objects.count(), 0)

    def test_fallback_stable_id_cannot_overwrite_another_source_entity(self):
        self.local_target.organism = "Mus musculus"
        self.local_target.save()
        collision = KnowledgeEntity.objects.create(entity_type="gene", stable_id="uniprot-gene:TP53",
            label="Original other-source record", organism="Mus musculus", source_release=self.legacy_release)
        run = self.make_run()
        with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
            preview_uniprot_sync(run)
            self.assertEqual(run.preview_summary["identifierConflicts"], 1)
            with self.assertRaisesRegex(ValidationError, "归属冲突"):
                apply_uniprot_sync(run)
        collision.refresh_from_db()
        self.assertEqual(collision.organism, "Mus musculus")
        self.assertEqual(collision.label, "Original other-source record")
        self.assertEqual(EntityIdentifier.objects.count(), 0)

    def test_explicit_human_gene_entity_can_be_reused(self):
        self.local_target.entity_type = "gene"
        self.local_target.save()
        self.preview_and_apply()
        self.assertEqual(EntityIdentifier.objects.get(namespace="uniprot", identifier="P04637").entity_id,
                         self.local_target.pk)

    def test_existing_external_accession_does_not_move_to_a_duplicate_human_symbol(self):
        EntityIdentifier.objects.create(entity=self.local_target, source_release=self.legacy_release,
                                        namespace="uniprot", identifier="P04637")
        KnowledgeEntity.objects.create(entity_type="protein", stable_id="other:TP53", label="Duplicate",
            organism="Homo sapiens", metadata={"symbol": "TP53"})
        run = self.preview_and_apply()
        self.assertEqual(run.preview_summary["ambiguousLocalGeneSymbols"], 1)
        self.assertEqual(EntityIdentifier.objects.get(namespace="uniprot", identifier="P04637").entity_id,
                         self.local_target.pk)

    def test_changed_symbol_for_an_existing_accession_requires_review(self):
        self.preview_and_apply()
        accession = EntityIdentifier.objects.get(namespace="uniprot", identifier="P04637")
        self.snapshot = self.build_snapshot(UniProtProtein("P04637", "Changed fixture", "OTHER", ("OTHER",)))
        run = self.make_run()
        with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
            preview_uniprot_sync(run)
            self.assertEqual(run.preview_summary["identifierConflicts"], 1)
            with self.assertRaisesRegex(ValidationError, "归属冲突"):
                apply_uniprot_sync(run)
        accession.refresh_from_db()
        self.assertEqual(accession.entity_id, self.local_target.pk)

    @patch("apps.sources.tasks.sync_source_run.delay")
    def test_api_rejects_conflicted_and_legacy_previews_before_queueing(self, delay):
        client = APIClient()
        client.force_authenticate(self.admin)
        run = self.make_run()
        with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
            preview_uniprot_sync(run)
        original_summary = dict(run.preview_summary)
        run.status = SyncRun.Status.SUCCEEDED
        for change, message in [("missing", "缺少身份核对依据"), ("conflict", "归属冲突")]:
            run.preview_summary = dict(original_summary)
            if change == "missing":
                run.preview_summary.pop("identityPlanSha256")
            else:
                run.preview_summary["identifierConflicts"] = 1
            run.save()
            response = client.post(reverse("sync-run-apply", args=[run.pk]), {}, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")
            self.assertIn(message, str(response.data["error"]["details"]))
            self.assertTrue(response.data["error"]["requestId"])
            delay.assert_not_called()
        run.preview_summary = original_summary
        run.save()
        response = client.post(reverse("sync-run-apply", args=[run.pk]), {}, format="json")
        self.assertEqual(response.status_code, 202)
        apply_run = SyncRun.objects.get(pk=response.data["run"]["id"])
        self.assertEqual(apply_run.preview_summary["identityPlanSha256"], original_summary["identityPlanSha256"])
        delay.assert_called_once()

    def test_preview_counts_missing_identifier_species_metadata_as_an_update(self):
        self.preview_and_apply()
        accession = EntityIdentifier.objects.get(namespace="uniprot", identifier="P04637")
        accession.metadata.pop("taxonId")
        accession.save()
        run = self.preview_and_apply()
        self.assertEqual(run.preview_summary["wouldUpdate"], 1)
        self.assertEqual(run.preview_summary["unchanged"], 1)
        accession.refresh_from_db()
        self.assertEqual(accession.metadata["taxonId"], 9606)
