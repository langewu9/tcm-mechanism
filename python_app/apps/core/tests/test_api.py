from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, MedicalCase, ResearchDataset


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
        self.task = AnalysisTask.objects.create(
            owner=self.owner,
            task_type=AnalysisTask.TaskType.NETWORK,
            dataset=self.dataset,
            result={"summary": "private analysis result"},
        )

    def test_private_records_are_not_visible_to_other_users(self):
        self.client.force_authenticate(self.other_user)

        dataset_response = self.client.get(reverse("dataset-list"))
        case_response = self.client.get(reverse("case-list"))
        task_response = self.client.get(reverse("analysis-task-list"))

        self.assertEqual(dataset_response.status_code, 200)
        self.assertEqual(dataset_response.data["count"], 0)
        self.assertEqual(case_response.status_code, 200)
        self.assertEqual(case_response.data["count"], 0)
        self.assertEqual(task_response.status_code, 200)
        self.assertEqual(task_response.data["count"], 0)

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
        task_response = self.client.get(reverse("analysis-task-detail", args=[self.task.pk]))

        self.assertEqual(dataset_response.status_code, 404)
        self.assertEqual(case_response.status_code, 404)
        self.assertEqual(task_response.status_code, 404)

    def test_superuser_can_view_all_research_records_and_results(self):
        admin = get_user_model().objects.create_superuser(
            username="platform-admin", email="admin@example.test", password="test-password-123"
        )
        self.client.force_authenticate(admin)

        datasets = self.client.get(reverse("dataset-list"))
        cases = self.client.get(reverse("case-list"))
        tasks = self.client.get(reverse("analysis-task-list"))

        self.assertEqual(datasets.data["count"], 1)
        self.assertEqual(cases.data["count"], 1)
        self.assertEqual(tasks.data["count"], 1)
        self.assertEqual(tasks.data["results"][0]["result"]["summary"], "private analysis result")

    def test_user_with_research_records_cannot_be_hard_deleted(self):
        with self.assertRaises(ProtectedError):
            self.owner.delete()

        self.assertTrue(get_user_model().objects.filter(pk=self.owner.pk).exists())


class ApiErrorContractTests(APITestCase):
    def test_unknown_api_route_uses_standard_json_error(self):
        response = self.client.get("/api/v1/route-that-does-not-exist/")

        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")
        self.assertIn("message", payload["error"])
        self.assertIn("requestId", payload["error"])

    def test_validation_failure_uses_standard_json_error(self):
        user = get_user_model().objects.create_user(username="researcher", password="test-password-123")
        self.client.force_authenticate(user)

        response = self.client.post(reverse("dataset-list"), {"description": "missing name"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("name", response.data["error"]["details"])


    def test_login_endpoint_rejects_requests_without_csrf_token(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        response = client.post(
            "/api/v1/auth/session/",
            {"username": "researcher", "password": "wrong"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "CSRF_FAILED")


    def test_react_session_login_uses_csrf_and_creates_server_session(self):
        from django.test import Client

        user = get_user_model().objects.create_user(username="researcher", password="test-password-123")
        client = Client(enforce_csrf_checks=True)
        csrf_response = client.get("/api/v1/auth/csrf/")

        response = client.post(
            "/api/v1/auth/session/",
            {"username": "researcher", "password": "test-password-123"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_response.json()["csrfToken"],
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], user.pk)
        self.assertTrue(client.get("/api/v1/auth/session/").json()["authenticated"])


    def test_unauthenticated_api_request_uses_authentication_error(self):
        response = self.client.get(reverse("dataset-list"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "AUTHENTICATION_REQUIRED")
