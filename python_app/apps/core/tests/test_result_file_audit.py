"""Inventory on disposable synthetic files; findings never change records/files."""
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, ResearchDataset, VisualizationArtifact
from apps.core.services.result_file_audit import audit_result_files
from . import test_artifact_integrity as fixtures


class ResultFileAuditTests(APITestCase):
    # Share only the synthetic setup, not the download tests themselves.
    setUp = fixtures.ArtifactIntegrityTests.setUp
    publish_manifest = fixtures.ArtifactIntegrityTests.publish_manifest

    def reasons(self, report):
        return {item["reason"] for item in report["findings"]}

    def orphan(self, suffix="unregistered.svg"):
        path = Path(self.temp.name, "analysis-artifacts", "unregistered", suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"SYNTHETIC_PRIVATE_CONTENT")
        return path

    def test_normal_local_inventory_is_complete_and_read_only(self):
        before = list(AnalysisTask.objects.values()), list(VisualizationArtifact.objects.values())
        original = Path(self.temp.name, self.key).read_bytes()
        report = audit_result_files()
        self.assertEqual(report["status"], "ok", report)
        self.assertTrue(report["complete"])
        self.assertTrue(report["readOnly"])
        self.assertEqual(report["counters"]["bytesHashed"], len(original))
        self.assertEqual(before, (list(AnalysisTask.objects.values()), list(VisualizationArtifact.objects.values())))
        self.assertEqual(Path(self.temp.name, self.key).read_bytes(), original)

    def test_missing_and_same_size_corrupt_files_are_distinguished(self):
        path = Path(self.temp.name, self.key)
        path.write_bytes(b"X" * len(self.content))
        self.assertIn("checksum_mismatch", self.reasons(audit_result_files()))
        path.unlink()
        self.assertIn("file_missing", self.reasons(audit_result_files()))
        self.assertEqual(VisualizationArtifact.objects.count(), 1)

    def test_uploaded_originals_are_checked_without_exposing_names_or_contents(self):
        ResearchDataset.objects.create(owner=self.owner, name="SYNTHETIC_PRIVATE_NAME", storage_key="research-datasets/1/missing.csv",
            byte_size=4, content_sha256=hashlib.sha256(b"test").hexdigest())
        report = audit_result_files()
        self.assertIn("file_missing", self.reasons(report))
        rendered = json.dumps(report)
        for text in ["SYNTHETIC_PRIVATE_NAME", "missing.csv", self.key, self.temp.name]:
            self.assertNotIn(text, rendered)

    def test_unregistered_file_is_a_review_candidate_and_is_never_removed(self):
        path = self.orphan()
        before = path.read_bytes()
        report = audit_result_files()
        self.assertEqual(report["counters"]["unregisteredCandidates"], 1)
        self.assertIn("unregistered_file_candidate", self.reasons(report))
        self.assertFalse(report["unregisteredFilesAreDeletionCandidates"])
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn("SYNTHETIC_PRIVATE_CONTENT", json.dumps(report))

    def test_active_render_path_is_not_claimed_to_be_a_safe_orphan(self):
        AnalysisTask.objects.filter(pk=self.render.pk).update(status="running")
        path = Path(self.temp.name, "analysis-artifacts", str(self.owner.pk), str(self.parent.pk), str(self.render.pk), "in-progress.pdf")
        path.write_bytes(b"SYNTHETIC_IN_PROGRESS")
        report = audit_result_files()
        self.assertIn("unregistered_path_with_active_task_id", self.reasons(report))
        self.assertIn("unpublished_record", self.reasons(report))
        self.assertEqual(report["pendingTasks"]["running"], 1)
        self.assertEqual(AnalysisTask.objects.get(pk=self.render.pk).status, "running")

    def test_missing_artifact_record_in_published_manifest_is_reported(self):
        self.artifact.delete()
        report = audit_result_files()
        self.assertIn("manifest_artifact_record_missing_or_mismatched", self.reasons(report))
        self.assertIn("unregistered_file_candidate", self.reasons(report))

    def test_reference_limit_does_not_misclassify_unchecked_registered_files(self):
        path = self.orphan("registered.csv")
        ResearchDataset.objects.create(owner=self.owner, name="synthetic", storage_key=str(path.relative_to(self.temp.name)),
            byte_size=path.stat().st_size, content_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        report = audit_result_files(max_records=1)
        self.assertFalse(report["complete"])
        self.assertIn("record_limit", report["incompleteReasons"])
        self.assertNotIn("unregistered_file_candidate", self.reasons(report))

    def test_byte_entry_and_finding_limits_never_claim_full_success(self):
        report = audit_result_files(max_bytes=1)
        self.assertFalse(report["complete"])
        self.assertIn("byte_limit", report["incompleteReasons"])
        self.assertLessEqual(report["counters"]["bytesHashed"], 1)
        report = audit_result_files(max_files=1)
        self.assertFalse(report["complete"])
        self.assertIn("filesystem_entry_limit", report["incompleteReasons"])
        self.orphan("one.svg"); self.orphan("two.svg")
        report = audit_result_files(max_findings=1)
        self.assertFalse(report["complete"])
        self.assertTrue(report["findingsTruncated"])
        self.assertEqual(len(report["findings"]), 1)

    def test_symbolic_links_are_not_followed_and_no_outside_contents_are_reported(self):
        path = Path(self.temp.name, self.key)
        path.unlink()
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside, "secret.svg"); target.write_bytes(self.content)
            path.symlink_to(target)
            report = audit_result_files()
            self.assertIn("unsafe_file_type", self.reasons(report))
            self.assertNotIn(outside, json.dumps(report))
            self.assertEqual(target.read_bytes(), self.content)

    def test_read_errors_are_incomplete_and_do_not_echo_private_paths(self):
        with patch("apps.core.services.result_file_audit.open_local_file", side_effect=PermissionError("PRIVATE_PATH")):
            report = audit_result_files()
        self.assertFalse(report["complete"])
        self.assertIn("storage_read_error", report["incompleteReasons"])
        self.assertNotIn("PRIVATE_PATH", json.dumps(report))

    @override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"}})
    def test_unsupported_storage_is_explicit_without_attempting_external_inventory(self):
        with self.assertNumQueries(0):
            report = audit_result_files()
        self.assertEqual(report["status"], "unsupported")
        self.assertFalse(report["complete"])

    def test_command_is_json_read_only_and_limits_are_validated(self):
        output = StringIO()
        call_command("audit_result_files", stdout=output)
        self.assertTrue(json.loads(output.getvalue())["readOnly"])
        for kwargs in [{"max_records": 0}, {"max_bytes": -1}, {"max_findings": True}, {"max_files": 1000001}]:
            with self.assertRaises(ValueError):
                audit_result_files(**kwargs)
