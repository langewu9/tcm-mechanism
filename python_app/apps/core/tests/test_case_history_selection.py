"""Exact historical case reads use synthetic records and never invoke a model."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, MedicalCase, MedicalCaseCandidate
from apps.core.services.case_analysis import case_input_sha256


@override_settings(SECURE_SSL_REDIRECT=False)
class CaseHistorySelectionTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="case-history-owner")
        self.other = User.objects.create_user(username="case-history-other")
        self.admin = User.objects.create_superuser(username="case-history-admin", email="history@example.test")
        self.client.force_authenticate(self.owner)
        self.case = MedicalCase.objects.create(owner=self.owner, title="SYNTHETIC history fixture",
            deidentified_text="合成医案，仅验证任务选择和权限。")
        self.second_case = MedicalCase.objects.create(owner=self.owner, title="SYNTHETIC other case",
            deidentified_text="合成的另一个医案。")
        self.private_case = MedicalCase.objects.create(owner=self.other, title="SYNTHETIC private case",
            deidentified_text="合成的其他账号医案。")
        self.old = self.task(self.case, "old", digest="0" * 64)
        self.latest = self.task(self.case, "latest")
        self.wrong_type = self.task(self.case, "wrong type", task_type="text_analysis")
        self.second_task = self.task(self.second_case, "other case")
        self.private_task = self.task(self.private_case, "private")
        self.old_candidate = self.candidate(self.old, "合成旧任务候选")
        self.latest_candidate = self.candidate(self.latest, "合成最新任务候选")
        self.url = reverse("case-analysis", args=[self.case.pk])
        for target in ("apps.core.services.case_analysis._local_model_response",
                       "apps.core.tasks.run_case_analysis_task.apply_async"):
            guard = patch(target, side_effect=AssertionError("Historical reads must not dispatch or call models"))
            guard.start()
            self.addCleanup(guard.stop)

    def task(self, case, name, *, digest=None, task_type="case_link", status="succeeded"):
        return AnalysisTask.objects.create(owner=case.owner, created_by=case.owner, medical_case=case,
            task_type=task_type, status=status, input_parameters={"analysisKind": "case_analysis",
                "caseContentSha256": digest if digest is not None else case_input_sha256(case)},
            result={"fixtureOnly": True, "savedName": name})

    def candidate(self, task, label):
        return MedicalCaseCandidate.objects.create(task=task, medical_case=task.medical_case,
            candidate_type="formula", label=label, match_status="unmatched", confidence="0.7",
            rank=1, evidence=[{"fixtureOnly": True}], review_status="pending")

    def test_exact_old_task_returns_its_candidates_result_and_stale_flag(self):
        response = self.client.get(self.url, {"task_id": self.old.pk})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["task"]["id"], self.old.pk)
        self.assertEqual(response.data["task"]["result"], self.old.result)
        self.assertEqual([row["id"] for row in response.data["candidates"]], [self.old_candidate.pk])
        self.assertTrue(response.data["stale"])
        latest = self.client.get(self.url, {"task_id": self.latest.pk})
        self.assertEqual(latest.data["task"]["id"], self.latest.pk)
        self.assertEqual([row["id"] for row in latest.data["candidates"]], [self.latest_candidate.pk])
        self.assertFalse(latest.data["stale"])

    def test_without_task_id_retains_latest_case_link_and_empty_case_behavior(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["task"]["id"], self.latest.pk)
        self.assertFalse(response.data["stale"])
        empty = MedicalCase.objects.create(owner=self.owner, title="SYNTHETIC empty", deidentified_text="合成")
        response = self.client.get(reverse("case-analysis", args=[empty.pk]))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data["task"])
        self.assertEqual(response.data["candidates"], [])
        self.assertFalse(response.data["stale"])

    def test_other_case_type_owner_or_missing_task_never_falls_back_to_latest(self):
        for task_id in [self.second_task.pk, self.wrong_type.pk, self.private_task.pk, 9007199254740991]:
            with self.subTest(task_id=task_id):
                response = self.client.get(self.url, {"task_id": task_id})
                self.assertEqual(response.status_code, 404, response.data)
                self.assertEqual(response.data["error"]["code"], "NOT_FOUND")
                self.assertNotIn("task", response.data)

    def test_other_account_cannot_read_task_even_with_known_case_and_task_ids(self):
        self.client.force_authenticate(self.other)
        response = self.client.get(self.url, {"task_id": self.old.pk})
        self.assertEqual(response.status_code, 404, response.data)
        self.assertEqual(response.data["error"]["code"], "NOT_FOUND")

    def test_admin_can_read_selected_other_owner_task_without_reassigning_it(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.url, {"task_id": self.old.pk})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["task"]["id"], self.old.pk)
        self.assertEqual(response.data["task"]["owner_id"], self.owner.pk)
        self.old.refresh_from_db()
        self.assertEqual(self.old.owner_id, self.owner.pk)

    def test_invalid_ids_use_validation_envelope(self):
        for invalid in ["", "0", "-1", "+1", "01", " 1", "1 ", "1.0", "1e0", "١", "１",
                        "NaN", "null", "9007199254740992", "1" * 100]:
            with self.subTest(task_id=invalid):
                response = self.client.get(self.url, {"task_id": invalid})
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")
                self.assertIn("task_id", response.data["error"]["details"])
        response = self.client.get(f"{self.url}?task_id={self.old.pk}&task_id={self.latest.pk}")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")

    def test_archived_case_preserves_read_only_history_and_rejects_new_analysis(self):
        self.case.archived_at = timezone.now()
        self.case.archived_by = self.owner
        self.case.save(update_fields=["archived_at", "archived_by"])
        response = self.client.get(self.url, {"task_id": self.old.pk})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["task"]["id"], self.old.pk)
        self.assertEqual(self.client.post(self.url, {"confirmLocalModel": True}, format="json").status_code, 404)

    def test_pending_and_failed_tasks_remain_the_requested_task(self):
        for status in ["queued", "running", "failed", "cancelled"]:
            with self.subTest(status=status):
                task = self.task(self.case, status, status=status)
                response = self.client.get(self.url, {"task_id": task.pk})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["task"]["id"], task.pk)
                self.assertEqual(response.data["task"]["status"], status)
                self.assertEqual(response.data["candidates"], [])

    def test_history_read_does_not_rewrite_business_records(self):
        models = [MedicalCase, AnalysisTask, MedicalCaseCandidate]
        before = [list(model.objects.order_by("pk").values()) for model in models]
        for params in [{"task_id": self.old.pk}, {"task_id": self.latest.pk}, {}]:
            self.assertEqual(self.client.get(self.url, params).status_code, 200)
        self.assertEqual([list(model.objects.order_by("pk").values()) for model in models], before)
