from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import MedicalCase, ResearchDataset


class PrivateWorkspaceApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="researcher-a", password="test-password-123")
        self.other_user = user_model.objects.create_user(username="researcher-b", password="test-password-123")
        self.dataset = ResearchDataset.objects.create(owner=self.owner, name="Proteomics cohort")
        self.case = MedicalCase.objects.create(
            owner=self.owner,
            title="De-identified case",
            deidentified_text="去标识化后的研究文本",
        )

    def test_private_records_are_not_visible_to_other_users(self):
        self.client.force_authenticate(self.other_user)

        dataset_response = self.client.get(reverse("dataset-list"))
        case_response = self.client.get(reverse("case-list"))

        self.assertEqual(dataset_response.status_code, 200)
        self.assertEqual(dataset_response.data["count"], 0)
        self.assertEqual(case_response.status_code, 200)
        self.assertEqual(case_response.data["count"], 0)

    def test_created_case_is_owned_by_authenticated_user(self):
        self.client.force_authenticate(self.other_user)

        response = self.client.post(
            reverse("case-list"),
            {"title": "New case", "deidentified_text": "无直接身份信息"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        new_case = MedicalCase.objects.get(pk=response.data["id"])
        self.assertEqual(new_case.owner, self.other_user)

    def test_dataset_and_case_detail_are_scoped_to_owner(self):
        self.client.force_authenticate(self.other_user)

        dataset_response = self.client.get(reverse("dataset-detail", args=[self.dataset.pk]))
        case_response = self.client.get(reverse("case-detail", args=[self.case.pk]))

        self.assertEqual(dataset_response.status_code, 404)
        self.assertEqual(case_response.status_code, 404)
