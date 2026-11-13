from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import ResearchDataset, ResearchUploadQuota, SensitiveAccessEvent
from apps.core.services.upload_quota import upload_quota_usage


CSV = b"Gene,log2FC,FDR\nTP53,2,0.01\n"


class UploadQuotaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.owner = users.objects.create_user(username="quota-owner")
        cls.other = users.objects.create_user(username="quota-other")
        cls.root = users.objects.create_superuser(username="quota-root", email="root@example.test")
        cls.staff = users.objects.create_user(username="quota-staff", is_staff=True)

    def setUp(self):
        cache.clear()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        self.media = Path(media.name)
        settings = override_settings(MEDIA_ROOT=media.name, STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": media.name}},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        })
        settings.enable()
        self.addCleanup(settings.disable)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_dataset_upload_has_separate_configurable_per_user_rate_limit(self):
        with patch("apps.core.throttling.DatasetUploadThrottle.get_rate", return_value="1/hour"):
            self.assertEqual(self.upload().status_code, 201)
            response = self.upload()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(ResearchDataset.objects.filter(owner=self.owner).count(), 1)
        self.assertEqual(len(self.files()), 1)

    def test_invalid_upload_attempt_also_consumes_rate_limit(self):
        with patch("apps.core.throttling.DatasetUploadThrottle.get_rate", return_value="1/hour"):
            invalid = self.api.post(reverse("dataset-list"), {
                "name": "Invalid upload", "file": SimpleUploadedFile("unsupported.bin", b"fixture"),
            }, format="multipart")
            self.assertEqual(invalid.status_code, 400)
            response = self.upload()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(ResearchDataset.objects.filter(owner=self.owner).count(), 0)
        self.assertEqual(self.files(), [])

    def upload(self, content=CSV):
        return self.api.post(reverse("dataset-list"), {
            "name": "Synthetic quota fixture", "file": SimpleUploadedFile("synthetic.csv", content),
        }, format="multipart")

    def files(self):
        return [path for path in self.media.rglob("*") if path.is_file()]

    def test_default_usage_and_limits_are_private_to_current_account(self):
        ResearchDataset.objects.create(owner=self.other, name="Other retained upload", byte_size=999)
        response = self.api.get(reverse("dataset-quota"), {"owner": self.other.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["limitBytes"], 1024 ** 3)
        self.assertEqual(response.data["limitDatasets"], 100)
        self.assertEqual(response.data["usedBytes"], 0)
        self.api.force_authenticate(None)
        self.assertEqual(self.api.get(reverse("dataset-quota")).status_code, 401)

    @override_settings(DATASET_COUNT_QUOTA=1)
    def test_count_limit_rejects_upload_before_storage_and_archive_does_not_free_quota(self):
        first = self.upload()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.api.delete(reverse("dataset-detail", args=[first.data["id"]])).status_code, 204)
        with patch("apps.core.services.dataset_uploads.store_dataset_upload") as store:
            response = self.upload()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["code"], "UPLOAD_QUOTA_EXCEEDED")
        store.assert_not_called()
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(ResearchDataset.objects.filter(owner=self.owner).count(), 1)
        self.api.force_authenticate(self.other)
        self.assertEqual(self.upload().status_code, 201)

    @override_settings(DATASET_STORAGE_QUOTA_BYTES=len(CSV))
    def test_exact_capacity_boundary_and_lowering_limit_keep_existing_files(self):
        self.assertEqual(self.upload().status_code, 201)
        response = self.upload()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["details"]["quota"]["usedBytes"], len(CSV))
        ResearchUploadQuota.objects.create(user=self.owner, storage_limit_mib=0)
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(upload_quota_usage(self.owner.pk)["remainingBytes"], 0)
        self.assertEqual(len(self.files()), 1)

    @override_settings(DATASET_COUNT_QUOTA=1)
    def test_invalid_upload_does_not_consume_quota_or_leave_a_file(self):
        self.assertEqual(self.upload(b"header\n").status_code, 400)
        self.assertEqual(upload_quota_usage(self.owner.pk)["usedDatasets"], 0)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.upload().status_code, 201)

    def test_individual_override_and_superuser_uploads_use_the_same_rules(self):
        ResearchUploadQuota.objects.create(user=self.owner, storage_limit_mib=2, dataset_limit=1)
        self.assertEqual(self.api.get(reverse("dataset-quota")).data["limitBytes"], 2 * 1024 ** 2)
        self.assertEqual(self.upload().status_code, 201)
        self.assertEqual(self.upload().status_code, 409)
        ResearchUploadQuota.objects.create(user=self.root, dataset_limit=0)
        self.api.force_authenticate(self.root)
        self.assertEqual(self.upload().status_code, 409)

    def test_failed_upload_audit_rolls_back_storage_and_usage(self):
        self.api.raise_request_exception = False
        with patch("apps.core.views.research.dataset_audit", side_effect=RuntimeError("synthetic audit failure")):
            self.assertEqual(self.upload().status_code, 500)
        self.assertEqual(self.files(), [])
        self.assertEqual(upload_quota_usage(self.owner.pk)["usedBytes"], 0)

    def quota_admin_post(self, storage_limit, dataset_limit):
        url = reverse("admin:auth_user_change", args=[self.owner.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        formset = response.context["inline_admin_formsets"][0].formset
        prefix = formset.prefix
        quota = ResearchUploadQuota.objects.filter(user=self.owner).first()
        joined = timezone.localtime(self.owner.date_joined)
        return self.client.post(url, {
            "username": self.owner.username, "email": self.owner.email,
            "first_name": "", "last_name": "", "is_active": "on",
            "date_joined_0": joined.strftime("%Y-%m-%d"), "date_joined_1": joined.strftime("%H:%M:%S"),
            f"{prefix}-TOTAL_FORMS": "1", f"{prefix}-INITIAL_FORMS": "1" if quota else "0",
            f"{prefix}-MIN_NUM_FORMS": "0", f"{prefix}-MAX_NUM_FORMS": "1",
            f"{prefix}-0-id": quota.pk if quota else "", f"{prefix}-0-user": self.owner.pk,
            f"{prefix}-0-storage_limit_mib": storage_limit, f"{prefix}-0-dataset_limit": dataset_limit,
            "_save": "Save",
        })

    def test_superuser_can_adjust_and_clear_override_in_existing_user_admin(self):
        self.client.force_login(self.root)
        response = self.quota_admin_post("2048", "200")
        self.assertEqual(response.status_code, 302)
        quota = ResearchUploadQuota.objects.get(user=self.owner)
        self.assertEqual((quota.storage_limit_mib, quota.dataset_limit, quota.updated_by_id), (2048, 200, self.root.pk))
        event = SensitiveAccessEvent.objects.get(action="quota_change")
        self.assertEqual(event.quota_changes["after"], {"storageLimitMiB": 2048, "datasetLimit": 200})
        self.assertEqual(upload_quota_usage(self.owner.pk)["limitBytes"], 2 * 1024 ** 3)
        self.assertEqual(self.quota_admin_post("", "").status_code, 302)
        self.assertEqual(upload_quota_usage(self.owner.pk)["limitBytes"], 1024 ** 3)
        self.assertEqual(upload_quota_usage(self.owner.pk)["limitDatasets"], 100)

    def test_staff_cannot_adjust_someone_elses_quota(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("admin:auth_user_change", args=[self.owner.pk]), {
            "upload_quota-0-storage_limit_mib": 9999,
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ResearchUploadQuota.objects.filter(user=self.owner).exists())


class ConcurrentUploadQuotaTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    @override_settings(DATASET_COUNT_QUOTA=1)
    def test_two_simultaneous_uploads_cannot_take_the_last_slot_twice(self):
        user = get_user_model().objects.create_user(username="quota-concurrent")
        barrier = Barrier(2)

        def upload():
            close_old_connections()
            try:
                api = APIClient()
                api.force_authenticate(user)
                barrier.wait(timeout=10)
                return api.post(reverse("dataset-list"), {
                    "name": "Synthetic concurrent upload", "file": SimpleUploadedFile("synthetic.csv", CSV),
                }, format="multipart").status_code
            finally:
                connections.close_all()

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media, STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": media}},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(upload) for _ in range(2)]
                statuses = sorted(future.result(timeout=20) for future in futures)
            self.assertEqual(statuses, [201, 409])
            self.assertEqual(ResearchDataset.objects.filter(owner=user).count(), 1)
            self.assertEqual(len([path for path in Path(media).rglob("*") if path.is_file()]), 1)
