import csv
import hashlib
import io
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.core.models import AnalysisSnapshotRow, AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease
from apps.core.services.complete_evidence import canonical, digest
from apps.core.services.herb_evidence import batch_herb_component_evidence
from apps.core.tasks import run_complete_evidence_task


@override_settings(SECURE_SSL_REDIRECT=False)
class CompleteEvidenceTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="complete-owner")
        self.other = get_user_model().objects.create_user(username="complete-other")
        self.admin = get_user_model().objects.create_superuser(username="complete-admin", email="test@example.test")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.source = DataSource.objects.create(slug="complete-fixture", name="Synthetic row provenance")
        self.release = SourceRelease.objects.create(source=self.source, version="v1", checksum_sha256="a" * 64,
            metadata={"connector": "sqlite-herb-compound-target"})
        self.herb = self.entity("herb", "合成药")
        self.compound = self.entity("compound", "合成成分")
        self.disease = self.entity("disease", "合成疾病")

    def entity(self, kind, label):
        return KnowledgeEntity.objects.create(stable_id=f"fixture:{kind}:{label}", label=label,
            entity_type=kind, source_release=self.release)

    def seed(self, size):
        targets = [KnowledgeEntity(stable_id=f"fixture:target:{index}", label=f"TARGET{index}",
            entity_type="protein", source_release=self.release) for index in range(size)]
        KnowledgeEntity.objects.bulk_create(targets)
        rows = []
        for index, target in enumerate(targets):
            for subject, object_, kind in ((self.herb, self.compound, "contains"), (self.compound, target, "targets")):
                rows.append(EvidenceRelation(subject=subject, object=object_, relation_type=kind,
                    source_release=self.release, source_record_id=f"row:{index}:{kind}", metadata={"sourceRowId": index}))
        EvidenceRelation.objects.bulk_create(rows, batch_size=250)
        EvidenceRelation.objects.create(subject=self.disease, object=targets[0], relation_type="disease_target",
            source_release=self.release, source_record_id="disease:1")
        return targets, rows

    def queue(self, kind="catalog_evidence"):
        if kind == "catalog_evidence":
            preview = batch_herb_component_evidence(query_type="herb", queries=[self.herb.label])
            url = "/api/v1/catalog/herb-evidence/analyses/"
            body = {"queryType": "herb", "queries": [self.herb.label], "expectedResultSha256": preview["resultSha256"], "complete": True}
        else:
            url = "/api/v1/analysis/network-pharmacology/"
            body = {"herb": self.herb.label, "disease": self.disease.label, "complete": True}
        with patch("apps.core.tasks.run_complete_evidence_task.apply_async") as dispatch:
            response = self.client.post(url, body, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        dispatch.assert_called_once_with(args=[response.data["id"]])
        return AnalysisTask.objects.get(pk=response.data["id"])

    def execute(self, task):
        result = run_complete_evidence_task(task.pk)
        task.refresh_from_db()
        self.assertEqual(result["status"], "succeeded", task.error_summary)
        self.assertEqual(task.status, "succeeded")
        for name, info in task.result["snapshot"]["tables"].items():
            rows = list(task.snapshot_rows.filter(table=name).values_list("payload", flat=True))
            self.assertEqual(info["count"], len(rows))
            self.assertEqual(info["sha256"], hashlib.sha256("".join(canonical(row) + "\n" for row in rows).encode()).hexdigest())

    def base(self, task):
        return f"/api/v1/research/analysis-tasks/{task.pk}"

    def test_full_input_and_export_exceed_both_preview_limits(self):
        targets, records = self.seed(4005)
        preview = batch_herb_component_evidence(query_type="herb", queries=[self.herb.label])
        self.assertTrue(preview["results"][0]["truncated"])
        legacy = self.client.post("/api/v1/catalog/herb-evidence/analyses/", {
            "queryType": "herb", "queries": [self.herb.label], "expectedResultSha256": preview["resultSha256"]}, format="json")
        self.assertEqual(legacy.status_code, 400)
        catalog = self.queue()
        self.execute(catalog)
        # The softcopyright catalogue also retains the linked disease layer.
        expected_ids = {record.pk for record in records} | set(EvidenceRelation.objects.filter(
            relation_type="disease_target").values_list("pk", flat=True))
        self.assertEqual(catalog.result["snapshot"]["tables"]["evidenceRecords"]["count"], len(expected_ids))
        self.assertTrue(catalog.result["limits"]["graphTruncated"])
        self.assertFalse(catalog.result["limits"]["queryTruncated"])
        statistics = {row["label"]: row["value"] for row in catalog.result["catalogSummary"]}
        self.assertEqual(statistics["靶点实体"], 4005)
        self.assertEqual(statistics["去重关系记录"], len(expected_ids))
        full_ids = set(catalog.snapshot_rows.filter(table="evidenceRecords").values_list("payload__id", flat=True))
        self.assertEqual(full_ids, expected_ids)
        network = self.queue("network_pharmacology")
        self.execute(network)
        self.assertEqual(network.result["summary"]["herbTargetCount"], 4005)
        self.assertEqual(network.result["summary"]["strictIntersectionCount"], 1)
        self.assertEqual(len(network.result["raw"]["herbLinks"]), 4000)
        self.assertTrue(network.result["rawLimits"]["tablesTruncated"]["herbLinks"])
        self.assertEqual(network.result["snapshot"]["tables"]["herbLinks"]["count"], 4005)
        self.assertEqual(network.result["snapshot"]["tables"]["evidenceRecords"]["count"], 8011)
        response = self.client.get(self.base(network) + "/snapshot-export/?table=herbLinks&file_format=csv")
        rows = list(csv.DictReader(io.StringIO(b"".join(response.streaming_content).decode("utf-8-sig"))))
        self.assertEqual(len(rows), 4005)
        self.assertEqual({int(row["relationId"]) for row in rows}, {record.pk for record in records if record.relation_type == "targets"})
        self.assertTrue(all(row["sourceChecksumSha256"] == "a" * 64 for row in rows))
        self.assertEqual(response["X-Snapshot-Sha256"], network.result["snapshot"]["sha256"])

    def test_immutable_pages_export_hash_and_owner_isolation(self):
        targets, _ = self.seed(25)
        task = self.queue()
        self.execute(task)
        before = digest(task.result)
        target = targets[0]
        target.label = "CHANGED IN LIVE CATALOGUE"
        target.save(update_fields=["label"])
        self.source.enabled = False
        self.source.save(update_fields=["enabled"])
        pages, ids = [], set()
        for page in (1, 2, 3):
            response = self.client.get(self.base(task) + f"/snapshot-rows/?page={page}&page_size=20")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 51)
            pages.extend(response.data["results"])
            ids.update(row["payload"]["id"] for row in response.data["results"])
        self.assertEqual(ids, set(EvidenceRelation.objects.values_list("pk", flat=True)))
        self.assertEqual([row["ordinal"] for row in pages], list(range(1, 52)))
        response = self.client.get(self.base(task) + "/snapshot-export/")
        lines = [json.loads(line) for line in b"".join(response.streaming_content).decode().splitlines()]
        manifest = lines[0]
        checksum = manifest["snapshot"].pop("sha256")
        self.assertEqual(checksum, digest({"parameters": manifest["parameters"], "result": manifest["result"], "manifest": manifest["snapshot"]}))
        self.assertFalse(any("CHANGED IN LIVE" in canonical(line) for line in lines))
        task.refresh_from_db()
        self.assertEqual(digest(task.result), before)
        for user, expected in ((self.other, 404), (None, 401), (self.admin, 200)):
            self.client.force_authenticate(user)
            for path in ("/snapshot-rows/", "/snapshot-export/?file_format=csv&table=evidenceRecords"):
                response = self.client.get(self.base(task) + path)
                self.assertEqual(response.status_code, expected)
                if expected == 200:
                    b"".join(response.streaming_content) if response.streaming else None

    def test_catalog_summary_renders_complete_input_and_legacy_frozen_rows_without_live_backfill(self):
        from apps.core.services.visualization import build_chart_payload
        self.seed(3)
        task = self.queue()
        self.execute(task)
        payload = build_chart_payload(task, "catalog_summary")
        counts = {row["label"]: row["value"] for row in payload["data"]}
        self.assertEqual(counts["靶点实体"], 3)
        self.assertEqual(counts["疾病实体"], 1)
        self.assertEqual(counts["去重关系记录"], 7)

        # Model a pre-fix immutable task, whose result did not store this field.
        task.result.pop("catalogSummary")
        manifest = task.result.pop("snapshot")
        manifest.pop("sha256")
        manifest["sha256"] = digest({"parameters": task.input_parameters, "result": task.result, "manifest": manifest})
        task.result["snapshot"] = manifest
        task.save(update_fields=["result"])
        before = digest(task.result)
        self.source.enabled = False
        self.source.save(update_fields=["enabled"])
        with patch.object(KnowledgeEntity.objects, "filter", side_effect=AssertionError("No live catalogue reads")):
            compatible = build_chart_payload(task, "catalog_summary")
        self.assertEqual(compatible["data"], payload["data"])
        task.refresh_from_db()
        self.assertEqual(digest(task.result), before)

    def test_legacy_summary_rejects_missing_or_corrupt_frozen_rows(self):
        from apps.core.services.visualization import build_chart_payload, VisualizationInputError
        self.seed(2)
        task = self.queue()
        self.execute(task)
        task.result.pop("catalogSummary")
        row = task.snapshot_rows.filter(table="entities").first()
        row.payload["type"] = "disease"
        row.save(update_fields=["payload"])
        with self.assertRaises(VisualizationInputError):
            build_chart_payload(task, "catalog_summary")
        task.snapshot_rows.filter(table="entities").delete()
        with self.assertRaises(VisualizationInputError):
            build_chart_payload(task, "catalog_summary")

    @override_settings(LOCAL_ANALYSIS_RELATION_LIMIT=2)
    def test_protection_limit_fails_without_publishing_partial_snapshot(self):
        self.seed(3)
        for kind in ("catalog_evidence", "network_pharmacology"):
            task = self.queue(kind)
            result = run_complete_evidence_task(task.pk)
            task.refresh_from_db()
            self.assertEqual(result["status"], "failed")
            self.assertIn("保护额度", task.error_summary)
            self.assertEqual(task.result, {})
            self.assertFalse(task.snapshot_rows.exists())

    def test_source_changed_since_preview_requires_new_search(self):
        self.seed(2)
        task = self.queue()
        self.herb.label = "changed"
        self.herb.save(update_fields=["label"])
        self.assertEqual(run_complete_evidence_task(task.pk)["status"], "failed")
        task.refresh_from_db()
        self.assertIn("重新检索", task.error_summary)
        self.assertFalse(task.snapshot_rows.exists())

    def test_worker_redelivery_and_mid_capture_failure_do_not_publish_rows(self):
        self.seed(2)
        task = self.queue()
        from apps.core.services.complete_evidence import _freeze_table
        calls = []
        def fail_after_first_table(*args):
            calls.append(args[1])
            if len(calls) > 1:
                raise RuntimeError("private filesystem path")
            return _freeze_table(*args)
        with patch("apps.core.services.complete_evidence._freeze_table", side_effect=fail_after_first_table):
            self.assertEqual(run_complete_evidence_task(task.pk)["status"], "failed")
        task.refresh_from_db()
        self.assertNotIn("private", task.error_summary)
        self.assertFalse(task.snapshot_rows.exists())
        good = self.queue()
        self.execute(good)
        count = good.snapshot_rows.count()
        before = digest(good.result)
        self.assertEqual(run_complete_evidence_task(good.pk)["status"], "skipped")
        good.refresh_from_db()
        self.assertEqual(good.snapshot_rows.count(), count)
        self.assertEqual(digest(good.result), before)

    def test_no_live_backfill_table_validation_and_safe_csv_cells(self):
        self.seed(1)
        task = self.queue()
        self.execute(task)
        self.assertEqual(self.client.get(self.base(task) + "/snapshot-rows/?table=../../config").status_code, 400)
        self.assertEqual(self.client.get(self.base(task) + "/snapshot-export/?file_format=csv").status_code, 400)
        old = AnalysisTask.objects.create(owner=self.owner, task_type="network", status="succeeded", result={"summary": {}})
        self.assertEqual(self.client.get(self.base(old) + "/snapshot-export/").status_code, 404)
        from apps.core.services.snapshot_exports import _cell
        self.assertEqual(_cell("=1+2"), "'=1+2")
        self.assertEqual(_cell(" \t@SUM(1)"), "' \t@SUM(1)")
        self.assertEqual(_cell("normal"), "normal")

    def test_complete_mode_keeps_eleventh_matching_source_entity(self):
        self.seed(1)
        extras = [KnowledgeEntity(stable_id=f"aaa:{index}", label=self.herb.label, entity_type="herb", source_release=self.release) for index in range(11)]
        KnowledgeEntity.objects.bulk_create(extras)
        preview = batch_herb_component_evidence(query_type="herb", queries=[self.herb.label])
        self.assertTrue(preview["results"][0]["truncated"])
        task = self.queue()
        self.execute(task)
        row = task.snapshot_rows.get(table="queries").payload
        self.assertEqual(len(row["matchedIds"]), 12)
        self.assertIn(self.herb.pk, row["matchedIds"])

    def test_full_candidate_source_export_keeps_more_than_thirty_sources(self):
        targets, _ = self.seed(1)
        EvidenceRelation.objects.bulk_create([EvidenceRelation(subject=self.compound, object=targets[0],
            relation_type="targets", source_release=self.release, source_record_id=f"extra:{index}",
            metadata={"sourceRowId": 0}) for index in range(34)])
        task = self.queue("network_pharmacology")
        self.execute(task)
        self.assertEqual(len(task.result["targets"][0]["sources"]), 30)
        # Every compound/target record keeps BOTH supporting edge references:
        # 35 * (one herb edge + one target edge) + one disease edge.
        self.assertEqual(task.result["snapshot"]["tables"]["targetSources"]["count"], 71)
        sources = list(task.snapshot_rows.filter(table="targetSources").values_list("payload", flat=True))
        self.assertEqual(len({row["relationId"] for row in sources}), 37)
        self.assertTrue(all(row["targetEntityId"] == targets[0].pk for row in sources))

    def test_linked_case_is_validated_again_in_worker_and_history_is_retained(self):
        from apps.core.models import MedicalCase, MedicalCaseCandidate
        from apps.core.services.case_analysis import case_input_sha256
        self.seed(1)
        formula = self.entity("formula", "合成方剂")
        EvidenceRelation.objects.create(subject=formula, object=self.herb, relation_type="contains_herb",
            source_release=self.release, source_record_id="formula:1")
        case = MedicalCase.objects.create(owner=self.owner, title="SYNTHETIC complete snapshot case", deidentified_text="合成医案，不含真实病例。")
        source = AnalysisTask.objects.create(owner=self.owner, task_type="case_link", medical_case=case,
            status="succeeded", input_parameters={"caseContentSha256": case_input_sha256(case)})
        candidate = MedicalCaseCandidate.objects.create(task=source, medical_case=case, candidate_type="formula",
            label=formula.label, entity=formula, match_status="exact", confidence="0.9", rank=1,
            evidence=[], review_status="accepted")
        body = {"herb": formula.label, "disease": self.disease.label, "complete": True,
                "source_case_id": case.pk, "source_candidate_id": candidate.pk}
        with patch("apps.core.tasks.run_complete_evidence_task.apply_async"):
            response = self.client.post("/api/v1/analysis/network-pharmacology/", body, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.execute(task)
        self.assertEqual(task.medical_case_id, case.pk)
        self.assertEqual(task.owner_id, self.owner.pk)
        self.assertEqual(task.input_parameters["sourceCandidateId"], candidate.pk)
        history = digest(task.result)
        with patch("apps.core.tasks.run_complete_evidence_task.apply_async"):
            response = self.client.post("/api/v1/analysis/network-pharmacology/", body, format="json")
        changed = AnalysisTask.objects.get(pk=response.data["id"])
        case.deidentified_text += "已更新"
        case.save(update_fields=["deidentified_text"])
        self.assertEqual(run_complete_evidence_task(changed.pk)["status"], "failed")
        changed.refresh_from_db()
        self.assertIn("重新分析", changed.error_summary)
        self.assertFalse(changed.snapshot_rows.exists())
        task.refresh_from_db()
        self.assertEqual(digest(task.result), history)

    def test_queue_failure_leaves_a_failed_record_not_a_queued_or_complete_task(self):
        from apps.core.services.complete_evidence import dispatch_complete_task
        from apps.core.exceptions import TaskQueueUnavailable
        task = AnalysisTask.objects.create(owner=self.owner, task_type="network", input_parameters={"complete": True})
        with patch("apps.core.tasks.run_complete_evidence_task.apply_async", side_effect=RuntimeError("private")):
            with self.assertRaises(TaskQueueUnavailable):
                dispatch_complete_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        self.assertEqual(task.result, {})
        self.assertNotIn("private", task.error_summary)

    def test_postgres_capture_uses_one_catalogue_view_across_stages(self):
        from django.db import connection, connections
        from concurrent.futures import ThreadPoolExecutor
        if connection.vendor != "postgresql":
            self.skipTest("Concurrent catalogue snapshot test requires PostgreSQL repeatable read.")
        targets, _ = self.seed(2)
        task = self.queue()
        from apps.core.services.complete_evidence import batch_herb_component_evidence as read
        reads = []
        def change_live_catalogue():
            try:
                KnowledgeEntity.objects.filter(pk=targets[0].pk).update(label="CHANGED CONCURRENTLY")
            finally:
                connections.close_all()
        def interleave(**kwargs):
            result = read(**kwargs)
            reads.append(True)
            if len(reads) == 1:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(change_live_catalogue).result(timeout=10)
            return result
        with patch("apps.core.services.complete_evidence.batch_herb_component_evidence", side_effect=interleave):
            self.execute(task)
        self.assertEqual(KnowledgeEntity.objects.get(pk=targets[0].pk).label, "CHANGED CONCURRENTLY")
        self.assertFalse(any("CHANGED CONCURRENTLY" in canonical(row) for row in task.snapshot_rows.values_list("payload", flat=True)))
