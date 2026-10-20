"""The management UI must not rewrite computed task records or provenance."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AnalysisTask, DataSource, SourceRelease


class AnalysisTaskAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(username="task-admin-owner")
        cls.other = user_model.objects.create_user(username="task-admin-other")
        cls.administrator = user_model.objects.create_superuser(
            username="task-admin-superuser", email="task-admin@example.test",
        )
        cls.staff = user_model.objects.create_user(username="task-admin-staff", is_staff=True)
        cls.staff.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="core", content_type__model="analysistask",
        ))
        source = DataSource.objects.create(
            slug="task-admin-fixture", name="Synthetic task admin fixture", access_mode="manual",
        )
        cls.release = SourceRelease.objects.create(source=source, version="synthetic-v1")
        cls.other_release = SourceRelease.objects.create(source=source, version="synthetic-v2")
        cls.task = AnalysisTask.objects.create(
            owner=cls.owner, created_by=cls.owner, task_type="network",
            status="succeeded", progress=100,
            input_parameters={"name": "Synthetic original input", "algorithmVersion": "fixture-v1"},
            result={"syntheticOriginalResult": [1, 2, 3]}, finished_at=timezone.now(),
        )
        cls.task.source_releases.add(cls.release)

    def task_snapshot(self):
        return (
            AnalysisTask.objects.values().get(pk=self.task.pk),
            list(self.task.source_releases.order_by("pk").values_list("pk", flat=True)),
        )

    def test_superuser_can_inspect_history_without_edit_controls(self):
        self.client.force_login(self.administrator)
        listing = self.client.get(reverse("admin:core_analysistask_changelist"))
        self.assertEqual(listing.status_code, 200)
        response = self.client.get(reverse("admin:core_analysistask_change", args=[self.task.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "syntheticOriginalResult")
        self.assertContains(response, "synthetic-v1")
        self.assertEqual(list(response.context["adminform"].form.fields), [])
        self.assertNotContains(response, 'name="_save"')
        self.assertNotContains(response, 'name="_continue"')
        self.assertNotContains(response, 'name="_addanother"')
        self.assertNotContains(response, 'class="deletelink"')

    def test_even_superuser_cannot_forge_task_update(self):
        self.client.force_login(self.administrator)
        before = self.task_snapshot()
        response = self.client.post(reverse("admin:core_analysistask_change", args=[self.task.pk]), {
            "owner": self.other.pk, "created_by": self.other.pk,
            "task_type": "network", "status": "failed", "progress": 0,
            "input_parameters": '{"name": "Forged input"}',
            "result": '{"forgedResult": true}', "error_summary": "Forged error",
            "source_releases": [self.other_release.pk], "_save": "Save",
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.task_snapshot(), before)

    def test_staff_model_permissions_do_not_reenable_task_writes(self):
        self.client.force_login(self.staff)
        before = self.task_snapshot()
        response = self.client.post(reverse("admin:core_analysistask_change", args=[self.task.pk]), {
            "owner": self.other.pk, "result": '{"forgedResult": true}', "_save": "Save",
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.task_snapshot(), before)

    def test_admin_cannot_manually_create_tasks(self):
        self.client.force_login(self.administrator)
        url = reverse("admin:core_analysistask_add")
        count = AnalysisTask.objects.count()
        self.assertEqual(self.client.get(url).status_code, 403)
        response = self.client.post(url, {
            "owner": self.owner.pk, "task_type": "network", "status": "succeeded",
            "progress": 100, "result": '{"forgedResult": true}',
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(AnalysisTask.objects.count(), count)

    def test_admin_cannot_delete_a_task(self):
        self.client.force_login(self.administrator)
        before = self.task_snapshot()
        url = reverse("admin:core_analysistask_delete", args=[self.task.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 403)
        self.assertEqual(self.task_snapshot(), before)

    def test_forged_bulk_delete_preserves_task_and_source_versions(self):
        self.client.force_login(self.administrator)
        before = self.task_snapshot()
        response = self.client.post(reverse("admin:core_analysistask_changelist"), {
            "action": "delete_selected", "_selected_action": [self.task.pk], "post": "yes",
        })
        self.assertIn(response.status_code, [200, 403])
        self.assertEqual(self.task_snapshot(), before)
