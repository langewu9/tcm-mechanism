"""Staff/model permissions must not bypass the platform-owner boundary."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from apps.core.models import AnalysisTask, MedicalCase
from apps.proteomics.models import ProteomicsRowResult


class PlatformAdminBoundaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.owner = users.objects.create_user(username="boundary-owner")
        cls.staff = users.objects.create_user(
            username="boundary-staff", password="synthetic-password-123", is_staff=True,
        )
        cls.staff.user_permissions.add(*Permission.objects.all())
        cls.root = users.objects.create_superuser(username="boundary-root", email="root@example.test")
        cls.case = MedicalCase.objects.create(
            owner=cls.owner, title="SYNTHETIC_PRIVATE_CASE", deidentified_text="SYNTHETIC_PRIVATE_BODY",
        )
        cls.task = AnalysisTask.objects.create(owner=cls.owner, task_type="proteomics", status="succeeded")
        cls.row = ProteomicsRowResult.objects.create(
            task=cls.task, row_index=0, original_label="SYNTHETIC_PRIVATE_ROW",
        )

    def test_staff_cannot_read_private_records_despite_all_model_permissions(self):
        self.client.force_login(self.staff)
        for url in (
            reverse("admin:index"), reverse("admin:core_medicalcase_changelist"),
            reverse("admin:core_medicalcase_change", args=[self.case.pk]),
            reverse("admin:core_analysistask_change", args=[self.task.pk]),
            reverse("admin:proteomics_proteomicsrowresult_change", args=[self.row.pk]),
            reverse("admin:auth_user_changelist"), reverse("admin:autocomplete"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("admin:login") + "?next="))
                self.assertNotIn(b"SYNTHETIC_PRIVATE", response.content)

    def test_admin_login_rejects_staff_credentials_without_creating_a_session(self):
        response = self.client.post(reverse("admin:login"), {
            "username": self.staff.username, "password": "synthetic-password-123", "next": "/django-admin/",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "只有平台超级管理员")

    def test_superuser_can_still_inspect_research_records_and_manage_users(self):
        self.client.force_login(self.root)
        case = self.client.get(reverse("admin:core_medicalcase_change", args=[self.case.pk]))
        self.assertEqual(case.status_code, 200)
        self.assertContains(case, "SYNTHETIC_PRIVATE_BODY")
        self.assertEqual(self.client.get(reverse("admin:auth_user_changelist")).status_code, 200)

    def test_proteomics_rows_cannot_be_edited_or_deleted_even_by_superuser(self):
        self.client.force_login(self.root)
        detail = reverse("admin:proteomics_proteomicsrowresult_change", args=[self.row.pk])
        response = self.client.get(detail)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["adminform"].form.fields), [])
        self.assertEqual(self.client.post(detail, {"original_label": "Forged"}).status_code, 403)
        delete = reverse("admin:proteomics_proteomicsrowresult_delete", args=[self.row.pk])
        self.assertEqual(self.client.post(delete, {"post": "yes"}).status_code, 403)
        self.row.refresh_from_db()
        self.assertEqual(self.row.original_label, "SYNTHETIC_PRIVATE_ROW")
