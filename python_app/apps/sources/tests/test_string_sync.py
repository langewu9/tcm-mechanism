import hashlib
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from apps.core.models import DataSource, EntityIdentifier, KnowledgeEntity, SourceRelease, SyncRun
from apps.sources.connectors.string import (
    StringCatalogError,
    StringCatalogSnapshot,
    StringProteinMapping,
    fetch_string_human_identifier_snapshot,
    parse_string_identifier_response,
)
from apps.sources.services import apply_string_sync, preview_string_sync
from apps.sources.tasks import sync_source_run


def mapping_payload(*records):
    return json.dumps(list(records)).encode("utf-8")


class StringIdentifierParserTests(SimpleTestCase):
    def test_parses_echo_query_and_human_string_id(self):
        records = mapping_payload({
            "queryIndex": 0,
            "queryItem": "P04637",
            "stringId": "9606.ENSP00000269305",
            "ncbiTaxonId": 9606,
            "preferredName": "TP53",
            "annotation": "tumor protein p53",
        })

        self.assertEqual(
            parse_string_identifier_response(records, ("P04637",)),
            {0: ("9606.ENSP00000269305", "TP53", "tumor protein p53")},
        )

    def test_rejects_wrong_taxon_identifier_or_echo(self):
        wrong_taxon = mapping_payload({
            "queryIndex": 0,
            "queryItem": "TP53",
            "stringId": "9606.ENSP00000269305",
            "ncbiTaxonId": 10090,
        })
        with self.assertRaisesRegex(StringCatalogError, "非人类"):
            parse_string_identifier_response(wrong_taxon, ("TP53",))

        wrong_echo = mapping_payload({
            "queryIndex": 0,
            "queryItem": "EGFR",
            "stringId": "9606.ENSP00000269305",
            "ncbiTaxonId": 9606,
        })
        with self.assertRaisesRegex(StringCatalogError, "不匹配"):
            parse_string_identifier_response(wrong_echo, ("TP53",))

        invalid_id = mapping_payload({
            "queryIndex": 0,
            "queryItem": "TP53",
            "stringId": "10090.ENSMUSP00000000001",
            "ncbiTaxonId": 9606,
        })
        with self.assertRaisesRegex(StringCatalogError, "无效"):
            parse_string_identifier_response(invalid_id, ("TP53",))

    def test_multiple_best_matches_are_left_unmapped(self):
        payload = mapping_payload(
            {"queryIndex": 0, "queryItem": "TP53", "stringId": "9606.ENSP00000000001", "ncbiTaxonId": 9606},
            {"queryIndex": 0, "queryItem": "TP53", "stringId": "9606.ENSP00000000002", "ncbiTaxonId": 9606},
        )
        self.assertEqual(parse_string_identifier_response(payload, ("TP53",)), {})


class StringIdentifierFetchTests(TestCase):
    def test_fetch_uses_human_entities_and_uniprot_accessions_and_checks_duplicate_local_names(self):
        source = DataSource.objects.create(slug="string-fetch-fixture", name="Fixture", access_mode="manual")
        release = SourceRelease.objects.create(source=source, version="fixture-v1")
        reviewed_source = DataSource.objects.get(slug="uniprot-human")
        reviewed_release = SourceRelease.objects.create(source=reviewed_source, version="2026_03+fixture")
        protein = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.PROTEIN,
            stable_id="protein:tp53",
            label="P53 protein",
            organism="Homo sapiens",
            source_release=release,
            metadata={"symbol": "TP53"},
        )
        EntityIdentifier.objects.create(
            entity=protein,
            source_release=reviewed_release,
            namespace="uniprot",
            identifier="P04637",
        )
        implicitly_human = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.PROTEIN,
            stable_id="legacy-target:EGFR",
            label="EGFR",
            source_release=release,
            metadata={"symbol": "EGFR"},
        )
        EntityIdentifier.objects.create(
            entity=implicitly_human,
            source_release=reviewed_release,
            namespace="uniprot",
            identifier="Q9H0H5",
        )
        # The same symbol on a separate local entity is intentionally excluded as ambiguous.
        for stable_id in ("gene:duplicate-a", "gene:duplicate-b"):
            KnowledgeEntity.objects.create(
                entity_type=KnowledgeEntity.EntityType.GENE,
                stable_id=stable_id,
                label="BRCA1",
                organism="Homo sapiens",
                metadata={"symbol": "BRCA1"},
            )
        KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.PROTEIN,
            stable_id="protein:mouse",
            label="TP53",
            organism="Mus musculus",
            metadata={"symbol": "TP53"},
        )
        KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.PROTEIN,
            stable_id="protein:untyped",
            label="EGFR",
            metadata={"symbol": "EGFR"},
        )

        class Response:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return self.payload[:limit]

        def open_request(request, timeout):
            from urllib.parse import parse_qs

            form = parse_qs(request.data.decode("utf-8"))
            queries = form["identifiers"][0].split("\r")
            self.assertEqual(form["species"], ["9606"])
            self.assertEqual(form["echo_query"], ["1"])
            self.assertEqual(queries, ["P04637", "Q9H0H5"])
            return Response(mapping_payload(*[
                {
                    "queryIndex": index,
                    "queryItem": query,
                    "stringId": f"9606.ENSP00000{269305 + index}",
                    "ncbiTaxonId": 9606,
                    "preferredName": "TP53" if query == "P04637" else "EGFR",
                    "annotation": "human protein",
                }
                for index, query in enumerate(queries)
            ]))

        with (
            patch("apps.sources.connectors.string._string_api_release", return_value=("12.5", "https://version-12-5.string-db.org/api", False)),
            patch("apps.sources.connectors.string._open_string", side_effect=open_request),
        ):
            snapshot = fetch_string_human_identifier_snapshot()

        self.assertEqual(snapshot.source_version, "12.5")
        self.assertEqual(snapshot.local_entity_count, 4)
        self.assertEqual(snapshot.submitted_query_count, 2)
        self.assertEqual(snapshot.ambiguous_local_count, 2)
        self.assertEqual(snapshot.unmapped_query_count, 0)
        self.assertEqual(len(snapshot.mappings), 2)
        self.assertEqual(snapshot.mappings[0].entity_id, protein.pk)
        self.assertEqual(snapshot.mappings[0].query, "P04637")
        self.assertEqual(snapshot.mappings[1].entity_id, implicitly_human.pk)
        self.assertEqual(len(snapshot.checksum_sha256), 64)


class StringIdentifierSyncTests(TestCase):
    def setUp(self):
        self.source = DataSource.objects.get(slug="string")
        self.admin = get_user_model().objects.create_superuser(
            username="string-admin",
            email="string-admin@example.test",
            password="test-password-123",
        )
        self.local_release = SourceRelease.objects.create(
            source=DataSource.objects.create(slug="string-sync-fixture", name="Fixture", access_mode="manual"),
            version="fixture-v1",
        )
        self.entity = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.PROTEIN,
            stable_id="local-protein:TP53",
            label="TP53",
            organism="Homo sapiens",
            source_release=self.local_release,
            metadata={"symbol": "TP53"},
        )
        self.snapshot = self.make_snapshot()

    def make_snapshot(self, string_id="9606.ENSP00000269305", version="12.5"):
        row = StringProteinMapping(
            entity_id=self.entity.pk,
            entity_stable_id=self.entity.stable_id,
            query="TP53",
            string_id=string_id,
            preferred_name="TP53",
            annotation="tumor protein p53",
        )
        checksum = hashlib.sha256(f"{version}:{self.entity.pk}:{string_id}".encode()).hexdigest()
        return StringCatalogSnapshot(
            mappings=(row,),
            source_version=version,
            api_endpoint=f"https://version-{version.replace('.', '-')}.string-db.org/api",
            checksum_sha256=checksum,
            local_entity_count=1,
            submitted_query_count=1,
            ambiguous_local_count=0,
            unmapped_query_count=0,
            ambiguous_remote_count=0,
        )

    def make_run(self):
        return SyncRun.objects.create(
            source=self.source,
            requested_by=self.admin,
            preview_summary={"mode": "preview", "connector": "string-human-identifier-crosswalk"},
        )

    def test_preview_is_read_only_and_records_version_and_diff(self):
        run = self.make_run()
        with patch("apps.sources.services._get_string_snapshot", return_value=self.snapshot):
            preview_string_sync(run)

        run.refresh_from_db()
        self.assertEqual(run.status, SyncRun.Status.PENDING)
        self.assertEqual(run.release.version, self.snapshot.release_version)
        self.assertEqual(run.cursor, self.snapshot.checksum_sha256)
        self.assertEqual(run.preview_summary["wouldCreate"], 1)
        self.assertEqual(run.preview_summary["identifierConflicts"], 0)
        self.assertFalse(EntityIdentifier.objects.filter(namespace="string").exists())

    def test_apply_adds_one_identifier_and_repeat_sync_is_idempotent(self):
        first = self.make_run()
        with patch("apps.sources.services._get_string_snapshot", return_value=self.snapshot):
            preview_string_sync(first)
            apply_string_sync(first)

        self.assertEqual(EntityIdentifier.objects.filter(namespace="string").count(), 1)
        identifier = EntityIdentifier.objects.get(namespace="string")
        self.assertEqual(identifier.entity_id, self.entity.pk)
        self.assertEqual(identifier.source_release.source, self.source)
        self.assertEqual(identifier.metadata["taxonId"], 9606)
        self.assertEqual(first.records_created, 1)

        second = self.make_run()
        with patch("apps.sources.services._get_string_snapshot", return_value=self.snapshot):
            preview_string_sync(second)
            self.assertEqual(second.preview_summary["wouldCreate"], 0)
            self.assertEqual(second.preview_summary["unchanged"], 1)
            apply_string_sync(second)

        self.assertEqual(EntityIdentifier.objects.filter(namespace="string").count(), 1)
        self.assertEqual(second.records_created, 0)
        self.assertEqual(second.records_updated, 0)

    def test_existing_identifier_owned_by_another_entity_is_not_reassigned(self):
        other = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.PROTEIN,
            stable_id="local-protein:OTHER",
            label="OTHER",
            organism="Homo sapiens",
            source_release=self.local_release,
            metadata={"symbol": "OTHER"},
        )
        EntityIdentifier.objects.create(
            entity=other,
            source_release=self.local_release,
            namespace="string",
            identifier="9606.ENSP00000269305",
        )
        run = self.make_run()
        with patch("apps.sources.services._get_string_snapshot", return_value=self.snapshot):
            preview_string_sync(run)
            self.assertEqual(run.preview_summary["identifierConflicts"], 1)
            with self.assertRaisesRegex(ValidationError, "归属冲突"):
                apply_string_sync(run)

        identifier = EntityIdentifier.objects.get(namespace="string")
        self.assertEqual(identifier.entity_id, other.pk)

    def test_changed_source_after_preview_requires_a_new_preview(self):
        run = self.make_run()
        with patch("apps.sources.services._get_string_snapshot", return_value=self.snapshot):
            preview_string_sync(run)
        changed = self.make_snapshot(string_id="9606.ENSP00000269306", version="12.6")
        with patch("apps.sources.services._get_string_snapshot", return_value=changed):
            with self.assertRaisesRegex(ValidationError, "预览后已变化"):
                apply_string_sync(run)
        self.assertFalse(EntityIdentifier.objects.filter(namespace="string").exists())


class StringIdentifierRoutingTests(TestCase):
    def setUp(self):
        self.source = DataSource.objects.get(slug="string")
        self.admin = get_user_model().objects.create_superuser(
            username="string-routing-admin",
            email="string-routing-admin@example.test",
            password="test-password-123",
        )

    def test_only_platform_admin_can_queue_string_sync_preview(self):
        client = APIClient()
        response = client.post(
            reverse("sync-source-preview", kwargs={"source_id": self.source.pk}),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

        client.force_authenticate(self.admin)
        with patch("apps.sources.views.enqueue_sync_run") as enqueue:
            response = client.post(
                reverse("sync-source-preview", kwargs={"source_id": self.source.pk}),
                {},
                format="json",
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["run"]["preview_summary"]["connector"], "string-human-identifier-crosswalk")
        enqueue.assert_called_once()

    def test_worker_dispatches_string_connector_preview(self):
        run = SyncRun.objects.create(
            source=self.source,
            requested_by=self.admin,
            preview_summary={"mode": "preview", "connector": "string-human-identifier-crosswalk"},
        )
        with patch("apps.sources.tasks.preview_string_sync") as preview:
            result = sync_source_run(run.pk)

        self.assertEqual(result["status"], SyncRun.Status.SUCCEEDED)
        preview.assert_called_once()
        run.refresh_from_db()
        self.assertEqual(run.status, SyncRun.Status.SUCCEEDED)
