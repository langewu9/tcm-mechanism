from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, MedicalCase, ResearchDataset


class AdminOverviewApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_superuser(
            username="platform-owner", email="owner@example.test", password="test-password-123"
        )
        self.researcher = user_model.objects.create_user(
            username="researcher", email="researcher@example.test", password="test-password-123"
        )
        self.dataset = ResearchDataset.objects.create(
            owner=self.researcher, name="Pilot dataset", row_count=4
        )
        MedicalCase.objects.create(
            owner=self.researcher, title="Pilot case", deidentified_text="去标识化内容"
        )
        AnalysisTask.objects.create(
            owner=self.researcher,
            task_type=AnalysisTask.TaskType.NETWORK,
            input_parameters={"name": "Herb target check"},
        )
        self.url = reverse("admin-overview")

    def test_overview_requires_platform_superuser(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.client.force_authenticate(self.researcher)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_platform_superuser_sees_user_asset_counts_and_recent_records(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        # The endpoint deliberately returns display names rather than usernames as a
        # second public identifier, matching the main admin page's selected fields.
        researcher = next(user for user in response.data["users"] if user["email"] == "researcher@example.test")
        self.assertEqual(researcher["name"], "researcher")
        self.assertEqual(researcher["role"], "RESEARCHER")
        self.assertTrue(researcher["is_active"])
        self.assertEqual(researcher["dataset_count"], 1)
        self.assertEqual(researcher["case_count"], 1)
        self.assertEqual(researcher["task_count"], 1)
        self.assertEqual(len(response.data["datasets"]), 1)
        self.assertEqual(response.data["datasets"][0]["owner_name"], "researcher")
        self.assertEqual(response.data["datasets"][0]["row_count"], 4)
        self.assertEqual(response.data["tasks"][0]["name"], "Herb target check")
        self.assertEqual(response.data["tasks"][0]["status"], AnalysisTask.Status.QUEUED)
        admin = next(user for user in response.data["users"] if user["email"] == "owner@example.test")
        self.assertEqual(admin["role"], "ADMIN")
