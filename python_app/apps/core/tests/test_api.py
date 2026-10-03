import hashlib
import json
import tempfile
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.storage import default_storage
from django.db.models.deletion import ProtectedError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.test import RequestFactory, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, MedicalCase, MedicalCaseAuditEvent, ResearchDataset, ResearcherProfile
from config.api_errors import ApiErrorEnvelopeMiddleware


class PrivateWorkspaceApiTests(APITestCase):
    def setUp(self):
        self.email_settings = override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            DEFAULT_FROM_EMAIL="noreply@example.test",
            PUBLIC_BASE_URL="https://research.example.test",
        )
        self.email_settings.enable()
        self.addCleanup(self.email_settings.disable)
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
            {
                "title": "New case",
                "deidentified_text": "无直接身份信息",
                "source_reference": "研究资料编号 R-2026-01",
                "owner_id": self.owner.pk,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        new_case = MedicalCase.objects.get(pk=response.data["id"])
        self.assertEqual(new_case.owner, self.other_user)
        self.assertEqual(new_case.source_reference, "研究资料编号 R-2026-01")
        self.assertEqual(response.data["owner_id"], self.other_user.pk)
        self.assertEqual(response.data["owner_username"], self.other_user.username)

    def test_dataset_upload_is_private_and_records_file_provenance(self):
        contents = b"gene,log2fc\nTP53,1.25\n"
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.client.force_authenticate(self.other_user)
            response = self.client.post(
                reverse("dataset-list"),
                {
                    "name": "Differential proteins",
                    "description": "Pilot upload",
                    "owner_id": self.owner.pk,
                    "file": SimpleUploadedFile("proteins.csv", contents, content_type="text/csv"),
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, 201)
            dataset = ResearchDataset.objects.get(pk=response.data["id"])
            self.assertEqual(dataset.owner, self.other_user)
            self.assertEqual(response.data["owner_username"], self.other_user.username)
            self.assertEqual(dataset.original_filename, "proteins.csv")
            self.assertEqual(dataset.byte_size, len(contents))
            self.assertEqual(dataset.content_sha256, hashlib.sha256(contents).hexdigest())
            self.assertTrue(default_storage.exists(dataset.storage_key))

            self.client.force_authenticate(self.owner)
            response = self.client.get(reverse("dataset-list"))
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["id"], self.dataset.pk)

            missing_permission_response = self.client.get(
                reverse("dataset-download", args=[dataset.pk])
            )
            self.assertEqual(missing_permission_response.status_code, 404)
            self.client.force_authenticate(self.other_user)
            download_response = self.client.get(reverse("dataset-download", args=[dataset.pk]))
            self.assertEqual(download_response.status_code, 200)
            self.assertEqual(b"".join(download_response.streaming_content), contents)

    def test_dataset_upload_rejects_unsupported_file_types(self):
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            reverse("dataset-list"),
            {"name": "Unsupported", "file": SimpleUploadedFile("payload.exe", b"not a dataset")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("file", response.data["error"]["details"])

    def test_dataset_upload_enforces_configured_size_limit(self):
        self.client.force_authenticate(self.owner)
        with override_settings(DATASET_UPLOAD_MAX_BYTES=4):
            response = self.client.post(
                reverse("dataset-list"),
                {"name": "Too large", "file": SimpleUploadedFile("large.csv", b"12345")},
                format="multipart",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(ResearchDataset.objects.filter(name="Too large").count(), 0)

    def test_only_dataset_owner_can_delete_and_deletion_removes_private_file(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.client.force_authenticate(self.owner)
            create_response = self.client.post(
                reverse("dataset-list"),
                {
                    "name": "Private dataset",
                    "file": SimpleUploadedFile("private.tsv", b"id\tvalue\nA\t1\n"),
                },
                format="multipart",
            )
            dataset = ResearchDataset.objects.get(pk=create_response.data["id"])
            storage_key = dataset.storage_key
            self.assertTrue(default_storage.exists(storage_key))

            self.client.force_authenticate(self.other_user)
            forbidden_delete = self.client.delete(reverse("dataset-detail", args=[dataset.pk]))
            self.assertEqual(forbidden_delete.status_code, 404)
            self.assertTrue(default_storage.exists(storage_key))

            self.client.force_authenticate(self.owner)
            delete_response = self.client.delete(reverse("dataset-detail", args=[dataset.pk]))
            self.assertEqual(delete_response.status_code, 204)
            self.assertFalse(default_storage.exists(storage_key))

    def test_case_update_and_delete_are_limited_to_the_owner(self):
        self.client.force_authenticate(self.other_user)

        update_response = self.client.patch(
            reverse("case-detail", args=[self.case.pk]), {"title": "Stolen"}, format="json"
        )
        delete_response = self.client.delete(reverse("case-detail", args=[self.case.pk]))

        self.assertEqual(update_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)
        self.case.refresh_from_db()
        self.assertEqual(self.case.title, "De-identified case")

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
        self.assertEqual(cases.data["results"][0]["owner_username"], self.owner.username)
        self.assertEqual(tasks.data["count"], 1)
        self.assertEqual(tasks.data["results"][0]["result"]["summary"], "private analysis result")

    def test_user_with_research_records_cannot_be_hard_deleted(self):
        with self.assertRaises(ProtectedError):
            self.owner.delete()

        self.assertTrue(get_user_model().objects.filter(pk=self.owner.pk).exists())

    def test_medical_case_create_update_and_delete_write_hash_only_audit_events(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(reverse("case-list"), {
            "title": "Audit case",
            "deidentified_text": "去标识化症状文本",
            "structured_data": {"diagnosis": "待审核证候"},
            "source_reference": "测试文献",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        case_id = response.data["id"]
        case = MedicalCase.objects.get(pk=case_id)
        created = MedicalCaseAuditEvent.objects.get(case=case, action=MedicalCaseAuditEvent.Action.CREATED)
        self.assertIn("deidentified_text", created.changed_fields)
        self.assertNotIn("去标识化症状文本", json.dumps(created.content_hashes, ensure_ascii=False))

        updated = self.client.patch(reverse("case-detail", args=[case_id]), {"research_notes": "修订说明"}, format="json")
        self.assertEqual(updated.status_code, 200)
        update_event = MedicalCaseAuditEvent.objects.get(case=case, action=MedicalCaseAuditEvent.Action.UPDATED)
        self.assertEqual(update_event.changed_fields, ["research_notes"])
        self.assertNotIn("修订说明", json.dumps(update_event.content_hashes, ensure_ascii=False))

        deleted = self.client.delete(reverse("case-detail", args=[case_id]))
        self.assertEqual(deleted.status_code, 204)
        deletion = MedicalCaseAuditEvent.objects.get(case_id_snapshot=case_id, action=MedicalCaseAuditEvent.Action.DELETED)
        self.assertIsNone(deletion.case)

    def test_case_audit_is_owner_private_and_superuser_can_review(self):
        self.client.force_authenticate(self.owner)
        created = self.client.post(reverse("case-list"), {
            "title": "Reviewable case", "deidentified_text": "去标识化症状",
            "structured_data": {"diagnosis": "候选证候"},
        }, format="json")
        case_id = created.data["id"]
        self.assertEqual(created.status_code, 201)
        self.assertEqual(self.client.get(reverse("case-audit", args=[case_id])).status_code, 200)

        self.client.force_authenticate(self.other_user)
        self.assertEqual(self.client.get(reverse("case-audit", args=[case_id])).status_code, 404)

        admin = get_user_model().objects.create_superuser(
            username="case-review-admin", email="case-admin@example.test", password="test-password-123"
        )
        self.client.force_authenticate(admin)
        reviewed = self.client.post(reverse("case-review", args=[case_id]), {"decision": "approve"}, format="json")
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.data["review_status"], MedicalCase.ReviewStatus.REVIEWED)
        case = MedicalCase.objects.get(pk=case_id)
        self.assertEqual(case.reviewed_by, admin)
        event = MedicalCaseAuditEvent.objects.get(case=case, action=MedicalCaseAuditEvent.Action.REVIEWED)
        self.assertEqual(event.actor, admin)

        self.client.force_authenticate(self.owner)
        edited = self.client.patch(reverse("case-detail", args=[case_id]), {"research_notes": "审核后补充材料"}, format="json")
        self.assertEqual(edited.status_code, 200)
        case.refresh_from_db()
        self.assertEqual(case.review_status, MedicalCase.ReviewStatus.DRAFT)
        self.assertIsNone(case.reviewed_by)


class ApiErrorContractTests(APITestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.addCleanup(cache.clear)
        self.email_settings = override_settings(
            DEBUG=True,
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            DEFAULT_FROM_EMAIL="noreply@example.test",
            PUBLIC_BASE_URL="https://research.example.test",
            ADMIN_NOTIFICATION_EMAILS=["admin@example.test"],
        )
        self.email_settings.enable()
        self.addCleanup(self.email_settings.disable)

    def test_unhandled_api_exception_is_returned_in_standard_error_envelope(self):
        request = RequestFactory().get("/api/v1/failing-endpoint/")

        def raise_error(_request):
            raise RuntimeError("private diagnostic detail")

        with self.assertLogs("config.api_errors", level="ERROR"):
            response = ApiErrorEnvelopeMiddleware(raise_error)(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(payload["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("private diagnostic detail", response.content.decode())
        self.assertEqual(response["X-Request-ID"], payload["error"]["requestId"])

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

    def test_invalid_login_uses_stable_401_error_code(self):
        response = self.client.post(
            reverse("auth-session"),
            {"username": "unknown-researcher", "password": "wrong-password"},
            format="json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "INVALID_CREDENTIALS")
        self.assertEqual(response["X-Request-ID"], response.data["error"]["requestId"])

    def test_researcher_registration_creates_inactive_non_admin_account(self):
        from django.contrib.auth import authenticate

        password = "Lemon-Cedar-47!river"
        response = self.client.post(
            "/api/v1/auth/register/",
            {
                "username": "evidence-reader",
                "email": " Reader@Example.org ",
                "password": password,
                "password_confirmation": password,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending_verification")
        user = get_user_model().objects.get(username="evidence-reader")
        self.assertEqual(user.email, "reader@example.org")
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password(password))
        self.assertIsNone(authenticate(username="evidence-reader", password=password))
        profile = ResearcherProfile.objects.get(user=user)
        self.assertIsNone(profile.email_verified_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["reader@example.org"])
        verification_url = next(
            line for line in mail.outbox[0].body.splitlines()
            if line.startswith("https://research.example.test/verify-email?")
        )
        token = parse_qs(urlsplit(verification_url).query)["token"][0]
        verified = self.client.post(
            reverse("auth-verify-email"), {"token": token}, format="json"
        )
        self.assertEqual(verified.status_code, 200, verified.data)
        self.assertFalse(verified.data["accountActive"])
        profile.refresh_from_db()
        self.assertIsNotNone(profile.email_verified_at)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].to, ["admin@example.test"])
        replayed = self.client.post(
            reverse("auth-verify-email"), {"token": token}, format="json"
        )
        self.assertEqual(replayed.status_code, 200)
        self.assertEqual(replayed.data["status"], "already_verified")
        self.assertEqual(len(mail.outbox), 2)
        self.assertIsNone(authenticate(username="evidence-reader", password=password))

        user.is_active = True
        user.save(update_fields=["is_active"])
        self.assertEqual(authenticate(username="evidence-reader", password=password), user)

    def test_invalid_email_token_is_rejected_without_verifying_account(self):
        password = "Lemon-Cedar-47!river"
        response = self.client.post(
            reverse("auth-register"),
            {
                "username": "verify-reader",
                "email": "verify-reader@example.org",
                "password": password,
                "password_confirmation": password,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        user = get_user_model().objects.get(username="verify-reader")
        invalid = self.client.post(reverse("auth-verify-email"), {"token": "not-a-token"}, format="json")
        self.assertEqual(invalid.status_code, 400)
        self.assertIsNone(user.researcher_profile.email_verified_at)

    def test_expired_email_token_is_rejected_without_verifying_account(self):
        from unittest.mock import patch

        from django.conf import settings

        response = self.client.post(
            reverse("auth-register"),
            {
                "username": "expired-reader",
                "email": "expired-reader@example.org",
                "password": "Lemon-Cedar-47!river",
                "password_confirmation": "Lemon-Cedar-47!river",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        user = get_user_model().objects.get(username="expired-reader")
        verification_url = next(
            line for line in mail.outbox[0].body.splitlines()
            if line.startswith("https://research.example.test/verify-email?")
        )
        token = parse_qs(urlsplit(verification_url).query)["token"][0]

        with patch("django.core.signing.time.time", return_value=2_000_000_000):
            rejected = self.client.post(reverse("auth-verify-email"), {"token": token}, format="json")

        self.assertEqual(rejected.status_code, 400)
        user.researcher_profile.refresh_from_db()
        self.assertIsNone(user.researcher_profile.email_verified_at)

    def test_email_change_invalidates_old_verification_token(self):
        password = "Horizon-Pine-92!cobalt"
        response = self.client.post(
            reverse("auth-register"),
            {
                "username": "changed-email-reader",
                "email": "old-reader@example.org",
                "password": password,
                "password_confirmation": password,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        verification_url = next(
            line for line in mail.outbox[-1].body.splitlines()
            if line.startswith("https://research.example.test/verify-email?")
        )
        token = parse_qs(urlsplit(verification_url).query)["token"][0]
        user = get_user_model().objects.get(username="changed-email-reader")
        user.email = "new-reader@example.org"
        user.save(update_fields=["email"])

        rejected = self.client.post(reverse("auth-verify-email"), {"token": token}, format="json")

        self.assertEqual(rejected.status_code, 400)
        self.assertIsNone(user.researcher_profile.email_verified_at)

    def test_resend_verification_response_does_not_reveal_account_existence(self):
        password = "Lemon-Cedar-47!river"
        registered = self.client.post(
            reverse("auth-register"),
            {
                "username": "resend-reader",
                "email": "resend-reader@example.org",
                "password": password,
                "password_confirmation": password,
            },
            format="json",
        )
        self.assertEqual(registered.status_code, 201)
        mail.outbox.clear()

        existing = self.client.post(
            reverse("auth-resend-verification"), {"email": "resend-reader@example.org"}, format="json"
        )
        missing = self.client.post(
            reverse("auth-resend-verification"), {"email": "missing@example.org"}, format="json"
        )

        self.assertEqual(existing.status_code, missing.status_code)
        self.assertEqual(existing.data, missing.data)
        self.assertEqual(len(mail.outbox), 1)

    def test_unverified_account_cannot_start_a_session_even_if_active_flag_is_set(self):
        user = get_user_model().objects.create_user(
            username="tampered-unverified", email="tampered@example.org",
            password="Lemon-Cedar-47!river", is_active=True,
        )
        ResearcherProfile.objects.create(user=user)

        response = self.client.post(
            reverse("auth-session"),
            {"username": user.username, "password": "Lemon-Cedar-47!river"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "EMAIL_NOT_VERIFIED")

    def test_email_delivery_failure_rolls_back_new_account(self):
        from unittest.mock import patch

        from apps.core.services.account_verification import EmailVerificationUnavailable

        with patch(
            "apps.core.views.auth.send_verification_email",
            side_effect=EmailVerificationUnavailable("test email delivery failure"),
        ):
            response = self.client.post(
                reverse("auth-register"),
                {
                    "username": "undeliverable-reader",
                    "email": "undeliverable@example.org",
                    "password": "Lemon-Cedar-47!river",
                    "password_confirmation": "Lemon-Cedar-47!river",
                },
                format="json",
            )

        self.assertEqual(response.status_code, 503)
        self.assertFalse(get_user_model().objects.filter(username="undeliverable-reader").exists())

    def test_admin_cannot_activate_unverified_or_keep_account_active_after_email_change(self):
        from django.contrib import admin
        from django.contrib.auth.admin import UserAdmin
        from django.test import RequestFactory

        from apps.core.admin import ResearcherUserAdmin

        user = get_user_model().objects.create_user(
            username="admin-verification", email="before@example.org",
            password="Lemon-Cedar-47!river", is_active=True,
        )
        profile = ResearcherProfile.objects.create(user=user)
        model_admin = ResearcherUserAdmin(get_user_model(), admin.site)
        request = RequestFactory().post("/admin/auth/user/")

        model_admin.save_model(request, user, form=None, change=True)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

        profile.email_verified_at = timezone.now()
        profile.save(update_fields=["email_verified_at"])
        user.is_active = True
        user.email = "after@example.org"
        model_admin.save_model(request, user, form=None, change=True)
        user.refresh_from_db()
        profile.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertIsNone(profile.email_verified_at)

    def test_researcher_registration_rejects_mismatched_and_weak_passwords(self):
        response = self.client.post(
            "/api/v1/auth/register/",
            {
                "username": "new-reader",
                "email": "new-reader@example.org",
                "password": "password",
                "password_confirmation": "different-password",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("password_confirmation", response.data["error"]["details"])
        self.assertFalse(get_user_model().objects.filter(username="new-reader").exists())

    def test_researcher_registration_requires_csrf_and_accepts_csrf_token(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        payload = {
            "username": "csrf-reader",
            "email": "csrf-reader@example.org",
            "password": "Lemon-Cedar-47!river",
            "password_confirmation": "Lemon-Cedar-47!river",
        }
        rejected = client.post("/api/v1/auth/register/", payload, content_type="application/json")
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(rejected.json()["error"]["code"], "CSRF_FAILED")
        for route, data in (
            ("/api/v1/auth/verify-email/", {"token": "invalid"}),
            ("/api/v1/auth/resend-verification/", {"email": "reader@example.org"}),
        ):
            protected = client.post(route, data, content_type="application/json")
            self.assertEqual(protected.status_code, 403)
            self.assertEqual(protected.json()["error"]["code"], "CSRF_FAILED")

        csrf_token = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        accepted = client.post(
            "/api/v1/auth/register/",
            json.dumps(payload),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(accepted.status_code, 201)
        self.assertFalse(get_user_model().objects.get(username="csrf-reader").is_active)

    def test_researcher_registration_is_rate_limited(self):
        from django.core.cache import cache

        cache.clear()
        password = "Lemon-Cedar-47!river"
        for index in range(5):
            response = self.client.post(
                "/api/v1/auth/register/",
                {
                    "username": f"rate-reader-{index}",
                    "email": f"rate-reader-{index}@example.org",
                    "password": password,
                    "password_confirmation": password,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 201)

        limited = self.client.post(
            "/api/v1/auth/register/",
            {
                "username": "rate-reader-over-limit",
                "email": "rate-reader-over-limit@example.org",
                "password": password,
                "password_confirmation": password,
            },
            format="json",
        )
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.data["error"]["code"], "RATE_LIMITED")
        self.assertFalse(get_user_model().objects.filter(username="rate-reader-over-limit").exists())


    def test_react_session_login_uses_csrf_and_creates_server_session(self):
        from django.test import Client, override_settings

        user = get_user_model().objects.create_user(username="researcher", password="test-password-123")
        client = Client(enforce_csrf_checks=True)
        with override_settings(CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:5173", "http://localhost:5173"]):
            csrf_response = client.get("/api/v1/auth/csrf/", HTTP_HOST="127.0.0.1:8020")

        with override_settings(CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:5173", "http://localhost:5173"]):
            response = client.post(
                "/api/v1/auth/session/",
                {"username": "researcher", "password": "test-password-123"},
                content_type="application/json",
                HTTP_HOST="127.0.0.1:8020",
                HTTP_ORIGIN="http://127.0.0.1:5173",
                HTTP_X_CSRFTOKEN=csrf_response.json()["csrfToken"],
            )
            session_response = client.get("/api/v1/auth/session/", HTTP_HOST="127.0.0.1:8020")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], user.pk)
        self.assertTrue(session_response.json()["authenticated"])


    def test_unauthenticated_api_request_uses_authentication_error(self):
        response = self.client.get(reverse("dataset-list"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "AUTHENTICATION_REQUIRED")

    def test_dataset_mutation_requires_csrf_for_cookie_authenticated_session(self):
        from django.test import Client

        user = get_user_model().objects.create_user(username="upload-researcher", password="test-password-123")
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        url = reverse("dataset-list")

        rejected = client.post(
            url,
            {"name": "Missing token", "file": SimpleUploadedFile("missing.csv", b"x\n1\n")},
        )
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(rejected.json()["error"]["code"], "CSRF_FAILED")

        csrf_token = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        accepted = client.post(
            url,
            {"name": "CSRF verified", "file": SimpleUploadedFile("valid.csv", b"x\n1\n")},
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(ResearchDataset.objects.get(pk=accepted.json()["id"]).owner, user)
