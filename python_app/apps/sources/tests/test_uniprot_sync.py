import hashlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

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
            source_release=self.legacy_release,
            metadata={"source": self.local_source.slug, "symbol": "TP53"},
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

        second = SyncRun.objects.create(
            source=self.source,
            release=run.release,
            cursor=run.cursor,
            preview_summary={"mode": "apply", "basedOn": run.pk},
        )
        repeat_preview = self.make_run()
        with patch("apps.sources.services._get_uniprot_snapshot", return_value=self.snapshot):
            preview_uniprot_sync(repeat_preview)
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
