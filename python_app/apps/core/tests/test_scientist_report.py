import ast
import csv
import io
import json
from pathlib import Path
import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease
from apps.core.services.complete_evidence import canonical, digest
from apps.core.tasks import run_research_assistant_task


@override_settings(SECURE_SSL_REDIRECT=False)
class ScientistReportTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="scientist-owner")
        self.other = get_user_model().objects.create_user(username="scientist-other")
        self.admin = get_user_model().objects.create_superuser(username="scientist-admin", email="test@example.test")
        self.client = APIClient(); self.client.force_authenticate(self.user)
        self.source = DataSource.objects.create(slug="scientist-fixture", name="Synthetic source")
        self.release = SourceRelease.objects.create(source=self.source, version="v1", checksum_sha256="a" * 64,
            metadata={"connector": "sqlite-herb-compound-target"})
        self.herbs = [self.entity("herb", label) for label in ["合成药甲", "合成药乙"]]
        self.compounds = [self.entity("compound", label) for label in ["合成成分甲", "合成成分乙"]]
        self.targets = [self.entity("protein", label) for label in ["SHARED", "HERB_ONLY"]]
        self.disease = self.entity("disease", "合成疾病")
        for index in range(2):
            self.edge(self.herbs[index], self.compounds[index], "contains", index + 1)
            self.edge(self.compounds[index], self.targets[index], "targets", index + 1)
        self.disease_edge = self.edge(self.disease, self.targets[0], "disease_target", 3)
        self.body = {"mode": "scientist_hypothesis", "question": "合成方药有哪些本地证据？",
                     "disease": self.disease.label, "formula": "合成药甲、合成药乙", "focus": "来源核对"}

    def entity(self, kind, label, **kwargs):
        return KnowledgeEntity.objects.create(entity_type=kind, label=label, stable_id=kwargs.pop("stable_id", f"fixture:{kind}:{label}"),
            source_release=kwargs.pop("source_release", self.release), **kwargs)

    def edge(self, subject, object_, kind, row, release=None):
        return EvidenceRelation.objects.create(subject=subject, object=object_, relation_type=kind,
            source_release=release or self.release, source_record_id=f"row:{row}:{kind}", metadata={"sourceRowId": row})

    def queue(self, **changes):
        with patch("apps.core.tasks.run_research_assistant_task.apply_async") as dispatch:
            response = self.client.post("/api/v1/research/assistant/", {**self.body, **changes}, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        dispatch.assert_called_once_with(args=[response.data["id"]])
        return AnalysisTask.objects.get(pk=response.data["id"])

    def execute(self, task):
        with patch("apps.core.services.research_assistant._validated_model_text", side_effect=AssertionError("No model")), \
             patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("No network")):
            status = run_research_assistant_task(task.pk)
        task.refresh_from_db()
        self.assertEqual(status["status"], "succeeded", task.error_summary)
        self.assertEqual(task.status, "succeeded")
        return task.result

    def test_local_report_matches_frozen_main_factual_counts_for_shared_identity_fixture(self):
        # Execute only the two frozen pure definitions, with the SAME fixture
        # projected as legacy search results. Never import/run legacy servers.
        path = Path(__file__).resolve().parent / "fixtures/scientist_main_reference.py"
        tree = ast.parse(path.read_text())
        definitions = [item for item in tree.body if isinstance(item, ast.FunctionDef)
                       and item.name in {"_parse_formula", "scientist_hypothesis"}]
        namespace = {"re": re, "_clean": lambda value: str(value).strip(),
            "search_disease": lambda *a, **k: {"targets": ["SHARED"], "herbs": []},
            "search_herb": lambda name, **k: {"targets": ["SHARED"] if name == "合成药甲" else ["HERB_ONLY"],
                "components": ["合成成分甲"] if name == "合成药甲" else ["合成成分乙"],
                "counts": {"components": 1, "targets": 1}},
            "intersect_targets": lambda left, right: {"intersection": sorted(set(left) & set(right))}}
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(path), "exec"), namespace)
        legacy = namespace["scientist_hypothesis"](self.body["question"], self.body["disease"], self.body["formula"], self.body["focus"])
        task = self.queue(owner=self.other.pk, useModel=False)
        self.assertEqual(task.owner, self.user); self.assertEqual(task.created_by, self.user)
        result = self.execute(task)
        for field in ["disease_target_count", "formula_target_count", "intersection_count"]:
            self.assertEqual(result["results"][field], legacy["results"][field])
        self.assertEqual(result["results"]["top_intersection_targets"], ["SHARED"])
        self.assertFalse(result["externalCalls"]); self.assertIsNone(result["model"])
        self.assertEqual([item["sourceReleaseId"] for item in result["references"]], [self.release.pk])
        self.assertNotIn("ChEMBL 36", canonical(result["references"]))
        self.assertEqual([row["target_count"] for row in result["evidence"]["herb_summaries"]], [1, 1])
        self.assertEqual(set(task.source_releases.values_list("pk", flat=True)), {self.release.pk})

    def test_same_label_different_source_identity_is_not_a_strict_intersection(self):
        source = DataSource.objects.create(slug="scientist-other-source", name="Other source")
        release = SourceRelease.objects.create(source=source, version="v2")
        other_target = self.entity("protein", "SHARED", stable_id="other-source:SHARED", source_release=release)
        self.disease_edge.object = other_target; self.disease_edge.save(update_fields=["object"])
        result = self.execute(self.queue())
        self.assertEqual(result["results"]["intersection_count"], 0)
        self.assertEqual(result["results"]["top_intersection_targets"], [])
        self.assertFalse(result["authorityIdentityVerified"])

    def test_missing_data_is_an_explicit_empty_report_without_fabricated_references(self):
        result = self.execute(self.queue(disease="不存在疾病", formula="不存在中药"))
        self.assertEqual(result["results"]["formula_target_count"], 0)
        self.assertEqual(result["results"]["disease_target_count"], 0)
        self.assertEqual(result["references"], [])
        self.assertIn("没有可用来源关系", " ".join(result["uncertainties"]))
        self.assertEqual(result["experiments"]["status"], "not_run")

    def test_no_strict_target_fallback_and_unmatched_input_is_preserved(self):
        result = self.execute(self.queue(formula="合成药乙、未知药"))
        self.assertEqual(result["results"]["formula_target_count"], 1)
        self.assertEqual(result["results"]["intersection_count"], 0)
        self.assertEqual(result["results"]["top_intersection_targets"], [])
        self.assertIn("未知药", " ".join(result["uncertainties"]))

    def test_shared_compound_does_not_import_other_herb_source_rows(self):
        other_herb = self.entity("herb", "另一味药")
        other_target = self.entity("protein", "OTHER_HERB_TARGET")
        self.edge(other_herb, self.compounds[0], "contains", 99)
        self.edge(self.compounds[0], other_target, "targets", 99)
        result = self.execute(self.queue(formula=self.herbs[0].label))
        self.assertEqual(result["results"]["formula_target_count"], 1)
        self.assertEqual(result["evidence"]["herb_summaries"][0]["target_count"], 1)

    def test_display_limit_does_not_limit_frozen_strict_targets(self):
        for index in range(35):
            target = self.entity("protein", f"STRICT{index}")
            self.edge(self.herbs[0], self.compounds[0], "contains", 100 + index)
            self.edge(self.compounds[0], target, "targets", 100 + index)
            self.edge(self.disease, target, "disease_target", 200 + index)
        task = self.queue(); result = self.execute(task)
        self.assertEqual(result["results"]["intersection_count"], 36)
        self.assertEqual(len(result["results"]["top_intersection_targets"]), 30)
        self.assertTrue(result["results"]["intersection_display_truncated"])
        self.assertEqual(result["snapshot"]["tables"]["targets"]["count"], 36)
        for name, info in result["snapshot"]["tables"].items():
            rows = list(task.snapshot_rows.filter(table=name).values_list("payload", flat=True))
            self.assertEqual(info["count"], len(rows))

    def test_disabled_source_is_not_reported_as_current_evidence(self):
        self.source.enabled = False; self.source.save(update_fields=["enabled"])
        result = self.execute(self.queue())
        self.assertEqual(result["references"], [])
        self.assertEqual(result["results"]["intersection_count"], 0)

    def test_input_validation_never_creates_invalid_or_model_report_task(self):
        for changes in [{"useModel": True, "confirmModelSharing": True}, {"confirmModelSharing": True},
                        {"disease": ""}, {"formula": ""}, {"formula": "、".join(f"药{i}" for i in range(13))},
                        {"entityIds": [self.herbs[0].pk]}, {"focus": "bad\x00"}]:
            with self.subTest(changes=changes), patch("apps.core.tasks.run_research_assistant_task.apply_async") as dispatch:
                response = self.client.post("/api/v1/research/assistant/", {**self.body, **changes}, format="json")
                self.assertEqual(response.status_code, 400, response.data); dispatch.assert_not_called()
        self.assertEqual(AnalysisTask.objects.count(), 0)

    def test_original_formula_delimiters_and_duplicate_herbs(self):
        task = self.queue(formula="合成药甲，合成药甲;合成药乙\n")
        self.assertEqual(task.input_parameters["formulaHerbs"], ["合成药甲", "合成药乙"])
        result = self.execute(task)
        self.assertEqual(result["results"]["formula_target_count"], 2)

    def test_snapshot_export_recovery_and_permissions_use_saved_evidence(self):
        task = self.queue(); result = self.execute(task)
        saved = digest(result)
        self.source.enabled = False; self.source.save(update_fields=["enabled"])
        base = f"/api/v1/research/analysis-tasks/{task.pk}"
        export = self.client.get(base + "/snapshot-export/")
        lines = [json.loads(line) for line in b"".join(export.streaming_content).decode().splitlines()]
        manifest = lines[0]
        checksum = manifest["snapshot"].pop("sha256")
        self.assertEqual(checksum, digest({"parameters": manifest["parameters"], "result": manifest["result"], "manifest": manifest["snapshot"]}))
        self.assertEqual(manifest["result"]["references"][0]["sourceVersion"], "v1")
        response = self.client.get(base + "/snapshot-export/?table=reportSections&file_format=csv")
        rows = list(csv.DictReader(io.StringIO(b"".join(response.streaming_content).decode("utf-8-sig"))))
        self.assertEqual(len(rows), 12)
        self.assertEqual(self.client.get(base + "/").status_code, 200)
        self.assertEqual(run_research_assistant_task(task.pk)["status"], "skipped")
        task.refresh_from_db(); self.assertEqual(digest(task.result), saved)
        self.client.force_authenticate(self.other)
        for suffix in ["/", "/snapshot-export/", "/snapshot-rows/?table=reportSections"]:
            self.assertEqual(self.client.get(base + suffix).status_code, 404)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(base + "/").status_code, 200)
        task.refresh_from_db(); self.assertEqual(task.owner, self.user)

    @override_settings(LOCAL_ANALYSIS_RELATION_LIMIT=1)
    def test_limit_failure_does_not_publish_partial_report(self):
        task = self.queue()
        self.assertEqual(run_research_assistant_task(task.pk)["status"], "failed")
        task.refresh_from_db()
        self.assertEqual(task.result, {}); self.assertFalse(task.snapshot_rows.exists())
        self.assertIn("保护额度", task.error_summary)

    def test_freeze_failure_rolls_back_all_report_rows_and_sources(self):
        from apps.core.services.complete_evidence import _freeze_table
        def fail_after_write(*args):
            _freeze_table(*args)
            raise OSError("SYNTHETIC PRIVATE FAILURE")
        task = self.queue()
        with patch("apps.core.services.complete_evidence._freeze_table", side_effect=fail_after_write):
            self.assertEqual(run_research_assistant_task(task.pk)["status"], "failed")
        task.refresh_from_db()
        self.assertEqual(task.result, {}); self.assertFalse(task.snapshot_rows.exists())
        self.assertFalse(task.source_releases.exists())
        self.assertNotIn("PRIVATE", task.error_summary)

    @patch("apps.core.tasks.run_research_assistant_task.apply_async", side_effect=OSError("SYNTHETIC PRIVATE QUEUE"))
    def test_queue_failure_is_saved_and_does_not_expose_internal_error(self, _):
        response = self.client.post("/api/v1/research/assistant/", self.body, format="json")
        self.assertEqual(response.status_code, 503)
        task = AnalysisTask.objects.get(); self.assertEqual(task.status, "failed")
        self.assertEqual(task.result, {}); self.assertNotIn("PRIVATE", str(response.data))
