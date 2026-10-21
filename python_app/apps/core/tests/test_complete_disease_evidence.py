import csv
import hashlib
import io
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease
from apps.core.services.complete_evidence import canonical, digest
from apps.core.tasks import run_complete_evidence_task


class CompleteDiseaseEvidenceTests(TransactionTestCase):
    def setUp(self):
        # This suite runs against disposable DBs; no request may reach a live
        # development broker. Individual tests can override this patch locally.
        dispatch = patch("apps.core.tasks.run_complete_evidence_task.apply_async")
        dispatch.start()
        self.addCleanup(dispatch.stop)
        self.owner = get_user_model().objects.create_user(username="disease-full-owner")
        self.other = get_user_model().objects.create_user(username="disease-full-other")
        self.admin = get_user_model().objects.create_superuser(username="disease-full-admin", email="test@example.test")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.source = DataSource.objects.create(slug="synthetic-full-disease", name="SYNTHETIC disease snapshot fixture")
        self.release = SourceRelease.objects.create(source=self.source, version="v1", checksum_sha256="a" * 64)
        self.disease = self.entity("disease", "fixture:disease", "肺纤维化")

    def entity(self, kind, stable, label, **kwargs):
        return KnowledgeEntity.objects.create(entity_type=kind, stable_id=stable, label=label,
            source_release=self.release, **kwargs)

    def seed(self, count):
        targets = [KnowledgeEntity(entity_type="gene", stable_id=f"fixture:target:{index}",
            label="同名靶点" if index < 2 else f"TARGET{index}", source_release=self.release,
            metadata={"sourceEntityId": f"raw-target:{index}", "identifierStatus": "unverified_source_assertion"})
            for index in range(count)]
        KnowledgeEntity.objects.bulk_create(targets, batch_size=250)
        relations = [EvidenceRelation(subject=self.disease, object=target, relation_type="disease_target",
            evidence_type="synthetic", source_release=self.release, source_record_id=f"row:{index}",
            metadata={"sourceRowId": index, "sourceOrigin": "synthetic fixture"}) for index, target in enumerate(targets)]
        EvidenceRelation.objects.bulk_create(relations, batch_size=250)
        return targets, relations

    def preview(self):
        response = self.client.get("/api/v1/catalog/diseases/evidence-search/", {"query": self.disease.label})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def queue(self, preview=None, extra=None):
        data = {"query": self.disease.label, "expectedResultSha256": (preview or self.preview())["resultSha256"], **(extra or {})}
        with patch("apps.core.tasks.run_complete_evidence_task.apply_async") as dispatch:
            response = self.client.post("/api/v1/catalog/diseases/evidence-analyses/", data, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        dispatch.assert_called_once_with(args=[response.data["id"]])
        return AnalysisTask.objects.get(pk=response.data["id"])

    def execute(self, task):
        state = run_complete_evidence_task(task.pk)
        task.refresh_from_db()
        self.assertEqual(state["status"], "succeeded", task.error_summary)
        return task.result["snapshot"]

    def base(self, task):
        return f"/api/v1/research/analysis-tasks/{task.pk}"

    def test_full_scope_export_paging_and_frozen_identifiers_exceed_preview_cap(self):
        targets, records = self.seed(4005)
        preview = self.preview()
        self.assertTrue(preview["truncated"])
        self.assertEqual(preview["counts"]["relations"], 1200)
        task = self.queue(preview)
        manifest = self.execute(task)
        self.assertEqual(task.result["counts"], {"diseases": 1, "herbs": 0, "targets": 4005, "links": 4005, "relations": 4005})
        self.assertFalse(task.result["limits"]["queryTruncated"])
        expected_ids = {row.pk for row in records}
        self.assertEqual(set(task.snapshot_rows.filter(table="evidenceRecords").values_list("payload__id", flat=True)), expected_ids)
        self.assertEqual(set(task.snapshot_rows.filter(table="diseaseLinks").values_list("payload__targetId", flat=True)), {row.pk for row in targets})
        self.assertTrue(all(row["herbId"] is None for row in task.snapshot_rows.filter(table="diseaseLinks").values_list("payload", flat=True)))
        for name, info in manifest["tables"].items():
            payloads = list(task.snapshot_rows.filter(table=name).values_list("payload", flat=True))
            self.assertEqual(len(payloads), info["count"])
            self.assertEqual(hashlib.sha256("".join(canonical(row) + "\n" for row in payloads).encode()).hexdigest(), info["sha256"])
        response = self.client.get(self.base(task) + "/snapshot-export/?table=diseaseLinks&file_format=csv")
        rows = list(csv.DictReader(io.StringIO(b"".join(response.streaming_content).decode("utf-8-sig"))))
        self.assertEqual(len(rows), 4005)
        self.assertEqual({int(row["relationId"]) for row in rows}, expected_ids)
        for page, first in ((1, 1), (2, 21), (201, 4001)):
            response = self.client.get(self.base(task) + f"/snapshot-rows/?table=diseaseLinks&page_size=20&page={page}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 4005)
            self.assertEqual(response.data["results"][0]["ordinal"], first)
            self.assertEqual(response.data["snapshotSha256"], manifest["sha256"])

    def test_more_than_twenty_matches_and_false_synonym_keys_do_not_lose_source_entities(self):
        target = self.entity("gene", "fixture:one-target", "TARGET")
        extra = [self.entity("disease", f"fixture:other:{index}", self.disease.label) for index in range(20)]
        KnowledgeEntity.objects.bulk_create([KnowledgeEntity(entity_type="disease", stable_id=f"fixture:invalid:{index}",
            label=f"00 unrelated {index}", synonyms={self.disease.label: "not a matching value"}, source_release=self.release) for index in range(25)])
        EvidenceRelation.objects.create(subject=extra[-1], object=target, relation_type="disease_target",
            source_release=self.release, source_record_id="last-matched-entity")
        self.assertTrue(self.preview()["truncated"])
        task = self.queue()
        self.execute(task)
        self.assertEqual(task.result["counts"]["diseases"], 21)
        self.assertEqual(task.result["counts"]["relations"], 1)
        matched = task.snapshot_rows.get(table="queries").payload["matchedIds"]
        self.assertEqual(set(matched), {self.disease.pk, *(entity.pk for entity in extra)})

    def test_direct_triples_resolve_only_canonical_herb_identity_and_keep_unresolved_rows(self):
        target = self.entity("gene", "fixture:target", "TARGET")
        herb1 = self.entity("herb", "fixture:herb:one", "同名药")
        herb2 = self.entity("herb", "fixture:herb:two", "同名药")
        disabled = self.entity("herb", "fixture:herb:inactive", "同名药", is_active=False)
        for index, stable in enumerate((herb2.stable_id, "unknown:herb", disabled.stable_id, None)):
            EvidenceRelation.objects.create(subject=self.disease, object=target, relation_type="disease_herb_target",
                source_release=self.release, source_record_id=f"triple:{index}", metadata={"herbStableId": stable, "herbLabel": herb1.label})
        task = self.queue()
        self.execute(task)
        rows = list(task.snapshot_rows.filter(table="diseaseLinks").values_list("payload", flat=True))
        self.assertEqual(task.result["counts"]["herbs"], 1)
        self.assertEqual([row["herbId"] for row in rows], [herb2.pk, None, None, None])
        self.assertNotIn(herb1.pk, task.snapshot_rows.filter(table="entities").values_list("payload__id", flat=True))

    def test_preview_hash_binds_hidden_source_assertion_and_changed_data_rejects_queue_result(self):
        _, rows = self.seed(1)
        old = self.preview()
        task = self.queue(old)
        rows[0].metadata = {**rows[0].metadata, "sourceRowId": 999}
        rows[0].save(update_fields=["metadata"])
        self.assertNotEqual(self.preview()["resultSha256"], old["resultSha256"])
        self.assertEqual(run_complete_evidence_task(task.pk)["status"], "failed")
        task.refresh_from_db()
        self.assertIn("重新检索", task.error_summary)
        self.assertFalse(task.snapshot_rows.exists())

    @override_settings(LOCAL_ANALYSIS_RELATION_LIMIT=2)
    def test_workload_limit_fails_closed(self):
        self.seed(3)
        task = self.queue()
        self.assertEqual(run_complete_evidence_task(task.pk)["status"], "failed")
        task.refresh_from_db()
        self.assertIn("保护额度", task.error_summary)
        self.assertEqual(task.result, {})
        self.assertFalse(task.snapshot_rows.exists())

    def test_catalogue_changes_after_success_do_not_backfill_export_and_ownership_is_preserved(self):
        targets, _ = self.seed(2)
        task = self.queue(extra={"owner_id": self.other.pk, "created_by": self.other.pk})
        self.execute(task)
        self.assertEqual(task.owner_id, self.owner.pk)
        self.assertEqual(task.created_by_id, self.owner.pk)
        before = digest(task.result)
        targets[0].label = "MUTATED_LIVE_LABEL"
        targets[0].save(update_fields=["label"])
        self.source.enabled = False
        self.source.save(update_fields=["enabled"])
        response = self.client.get(self.base(task) + "/snapshot-export/")
        lines = [json.loads(line) for line in b"".join(response.streaming_content).decode().splitlines()]
        manifest = lines[0]["snapshot"]
        sha = manifest.pop("sha256")
        self.assertEqual(sha, digest({"parameters": lines[0]["parameters"], "result": lines[0]["result"], "manifest": manifest}))
        self.assertFalse(any("MUTATED_LIVE_LABEL" in canonical(line) for line in lines))
        for user, expected in ((self.other, 404), (None, 401), (self.admin, 200)):
            self.client.force_authenticate(user)
            for suffix in ("/snapshot-rows/", "/snapshot-export/"):
                response = self.client.get(self.base(task) + suffix)
                self.assertEqual(response.status_code, expected)
                if response.streaming:
                    b"".join(response.streaming_content)
        task.refresh_from_db()
        self.assertEqual(digest(task.result), before)

    def test_empty_match_and_zero_relations_are_distinct(self):
        isolated = self.queue()
        manifest = self.execute(isolated)
        self.assertEqual(manifest["tables"]["evidenceRecords"]["count"], 0)
        self.assertEqual(manifest["tables"]["entities"]["count"], 1)
        with patch("apps.core.tasks.run_complete_evidence_task.apply_async"):
            absent = self.client.post("/api/v1/catalog/diseases/evidence-analyses/", {
                "query": "NO_MATCH_COMPLETE_DISEASE", "expectedResultSha256": self.client.get(
                    "/api/v1/catalog/diseases/evidence-search/", {"query": "NO_MATCH_COMPLETE_DISEASE"}).data["resultSha256"]}, format="json")
        self.assertEqual(absent.status_code, 202)
        self.assertEqual(run_complete_evidence_task(absent.data["id"])["status"], "failed")
        self.assertFalse(AnalysisTask.objects.get(pk=absent.data["id"]).snapshot_rows.exists())

    def test_queue_input_validation_and_unavailable_broker(self):
        before = AnalysisTask.objects.count()
        for body in ({"query": "x"}, {"query": "x", "expectedResultSha256": "bad"},
                     {"query": "x" * 121, "expectedResultSha256": "a" * 64}):
            self.assertEqual(self.client.post("/api/v1/catalog/diseases/evidence-analyses/", body, format="json").status_code, 400)
        self.assertEqual(AnalysisTask.objects.count(), before)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post("/api/v1/catalog/diseases/evidence-analyses/", {}, format="json").status_code, 401)
        self.client.force_authenticate(self.owner)
        with patch("apps.core.tasks.run_complete_evidence_task.apply_async", side_effect=OSError("PRIVATE_BROKER_URL")):
            response = self.client.post("/api/v1/catalog/diseases/evidence-analyses/", {
                "query": self.disease.label, "expectedResultSha256": self.preview()["resultSha256"]}, format="json")
        self.assertEqual(response.status_code, 503)
        task = AnalysisTask.objects.latest("id")
        self.assertEqual(task.status, "failed")
        self.assertNotIn("PRIVATE", task.error_summary)

    def test_unsupported_complete_kind_is_rejected_without_publishing(self):
        task = AnalysisTask.objects.create(owner=self.owner, task_type="network", input_parameters={"complete": True, "analysisKind": "unknown"})
        self.assertEqual(run_complete_evidence_task(task.pk)["status"], "failed")
        task.refresh_from_db()
        self.assertIn("不支持", task.error_summary)
        self.assertFalse(task.snapshot_rows.exists())

    def test_postgres_repeatable_read_keeps_one_disease_view_during_capture(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL repeatable read.")
        from concurrent.futures import ThreadPoolExecutor
        from apps.core.services.disease_evidence import search_disease_evidence as read
        targets, _ = self.seed(2)
        task = self.queue()
        calls = []
        def change_live():
            try:
                KnowledgeEntity.objects.filter(pk=targets[0].pk).update(label="MUTATED_CONCURRENTLY")
            finally:
                connections.close_all()
        def interleave(*args, **kwargs):
            result = read(*args, **kwargs)
            calls.append(True)
            if len(calls) == 1:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(change_live).result(timeout=10)
            return result
        with patch("apps.core.services.disease_evidence.search_disease_evidence", side_effect=interleave):
            self.execute(task)
        self.assertEqual(KnowledgeEntity.objects.get(pk=targets[0].pk).label, "MUTATED_CONCURRENTLY")
        self.assertFalse(any("MUTATED_CONCURRENTLY" in canonical(row) for row in task.snapshot_rows.values_list("payload", flat=True)))
