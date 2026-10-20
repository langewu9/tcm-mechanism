from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404, HttpResponse, JsonResponse
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import path
from rest_framework.test import APIClient

from apps.core.checks import shared_control_checks
from apps.core.models import AnalysisTask, DataSource, ResearchDataset, SourceRelease
from apps.core.throttling import PlatformUserThrottle, ResearchSubmissionThrottle
from apps.core.views.auth import LoginSerializer
from config.parsers import BoundedJSONParser, PayloadTooLarge


def broken(request):
    raise RuntimeError("SYNTHETIC_PRIVATE_EXCEPTION")


def missing(request):
    raise Http404("SYNTHETIC_PRIVATE_PATH")


def raw_error(request):
    response = HttpResponse("SYNTHETIC_PROXY_BODY", status=429)
    response["Retry-After"] = "17"
    return response


urlpatterns = [path("api/broken/",broken),path("api/missing/",missing),path("api/raw-error/",raw_error),
               path("api/json-error/",lambda request:JsonResponse({"error":{"details":"SYNTHETIC_SECRET"}},status=500)),
               path("plain/",lambda request:HttpResponse("plain"))]


@override_settings(ROOT_URLCONF=__name__)
class ErrorBoundaryTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient(); self.client.raise_request_exception=False

    def test_unhandled_error_is_json_without_debug_traceback(self):
        response=self.client.get("/api/broken/")
        self.assertEqual(response.status_code,500)
        self.assertEqual(response.json()["error"]["code"],"INTERNAL_ERROR")
        self.assertNotContains(response,"SYNTHETIC_PRIVATE_EXCEPTION",status_code=500)
        self.assertEqual(response["X-Request-ID"],response.json()["error"]["requestId"])

    def test_explicit_json_500_cannot_expose_internal_details(self):
        response=self.client.get("/api/json-error/")
        self.assertIsNone(response.json()["error"]["details"])

    def test_plain_django_404_stays_404(self):
        response=self.client.get("/api/missing/")
        self.assertEqual(response.status_code,404)
        self.assertNotContains(response,"SYNTHETIC_PRIVATE_PATH",status_code=404)

    def test_raw_throttle_is_normalized_and_preserves_retry_after(self):
        response=self.client.get("/api/raw-error/")
        self.assertEqual(response.status_code,429)
        self.assertEqual(response["Retry-After"],"17")
        self.assertEqual(response.json()["error"]["code"],"RATE_LIMITED")

    def test_private_api_is_not_cacheable_even_when_error_or_anonymous(self):
        for url in ("/api/raw-error/","/api/missing/"):
            response=self.client.get(url)
            self.assertIn("no-store",response["Cache-Control"])
            self.assertIn("private",response["Cache-Control"])
            self.assertIn("Cookie",response["Vary"])
        self.assertNotIn("Cache-Control",self.client.get("/plain/"))

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=32)
    def test_request_limit_runs_before_the_view(self):
        response=self.client.post("/api/broken/",b"x"*33,content_type="application/json")
        self.assertEqual(response.status_code,413)
        self.assertEqual(response.json()["error"]["code"],"PAYLOAD_TOO_LARGE")

    def test_bad_content_length_is_not_a_server_error(self):
        response=self.client.generic("POST","/api/broken/",CONTENT_LENGTH="invalid")
        self.assertEqual(response.status_code,400)


class ParserAndConfigurationTests(SimpleTestCase):
    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=16)
    def test_stream_without_content_length_is_bounded(self):
        class RecordingStream(BytesIO):
            def read(self,size=-1):
                assert size==17
                return super().read(size)
        with self.assertRaises(PayloadTooLarge):
            BoundedJSONParser().parse(RecordingStream(b"["+b"1,"*30+b"1]"))

    def test_deep_json_is_a_client_error(self):
        from rest_framework.exceptions import ParseError
        with self.assertRaises(ParseError):
            BoundedJSONParser().parse(BytesIO(("["*2000+"0"+"]"*2000).encode()))

    def test_password_length_is_rejected_before_hashing(self):
        serializer=LoginSerializer(data={"username":"reader","password":"a"*1025})
        self.assertFalse(serializer.is_valid())

    @override_settings(DEBUG=False,SECRET_KEY="replace-with-example",CACHES={"default":{"BACKEND":"django.core.cache.backends.locmem.LocMemCache"}})
    def test_production_checks_flag_placeholder_and_nonshared_limits(self):
        self.assertEqual({item.id for item in shared_control_checks(None)},{"platform.E002","platform.W001"})


class QueryBudgetTests(TestCase):
    def setUp(self):
        cache.clear();self.addCleanup(cache.clear)
        self.owner=get_user_model().objects.create_user(username="framework-owner")
        self.other=get_user_model().objects.create_user(username="framework-other")
        self.client=APIClient();self.client.force_authenticate(self.owner)
        source=DataSource.objects.create(slug="framework-fixture",name="Synthetic framework fixture")
        self.release=SourceRelease.objects.create(source=source,version="v1")

    def tasks(self,count):
        for _ in range(count):
            task=AnalysisTask.objects.create(owner=self.owner,created_by=self.other,task_type="network")
            task.source_releases.add(self.release)

    def test_task_list_query_count_does_not_grow_per_record(self):
        self.tasks(1)
        with self.assertNumQueries(4):
            small=self.client.get("/api/v1/research/analysis-tasks/")
        self.tasks(19)
        with self.assertNumQueries(4):
            large=self.client.get("/api/v1/research/analysis-tasks/")
        self.assertEqual(len(large.data["results"]),20)
        self.assertEqual(large.data["results"][0]["source_releases"],[self.release.pk])

    def test_dataset_owner_labels_do_not_add_queries(self):
        ResearchDataset.objects.bulk_create([ResearchDataset(owner=self.owner,name=f"dataset {i}") for i in range(20)])
        with self.assertNumQueries(3):
            response=self.client.get("/api/v1/research/datasets/")
        self.assertEqual(len(response.data["results"]),20)

    def test_cross_owner_access_stays_denied_with_prefetch(self):
        task=AnalysisTask.objects.create(owner=self.other,task_type="network")
        response=self.client.get(f"/api/v1/research/analysis-tasks/{task.pk}/")
        self.assertEqual(response.status_code,404)

    def test_file_upload_can_exceed_json_budget_without_bypassing_file_limit(self):
        content = b"Gene,Value,Note\n" + (b"TP53,2," + b"a" * 220 + b"\n") * 5000
        self.assertGreater(len(content), 1024 * 1024)
        with TemporaryDirectory() as root, override_settings(MEDIA_ROOT=root):
            response = self.client.post(
                "/api/v1/research/datasets/",
                {"name": "Synthetic upload budget test", "file": SimpleUploadedFile("synthetic.csv", content)},
                format="multipart",
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["byte_size"], len(content))

    def test_non_text_json_charset_is_a_client_error(self):
        response = self.client.post(
            "/api/v1/research/cases/", b"e30=", content_type="application/json; charset=base64_codec",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    @patch.object(PlatformUserThrottle,"get_rate",return_value="2/min")
    def test_user_limit_has_unified_error_and_retry_after(self, _rate):
        url="/api/v1/research/datasets/"
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.get(url).status_code,200)
        response=self.client.get(url)
        self.assertEqual(response.status_code,429)
        self.assertEqual(response.data["error"]["code"],"RATE_LIMITED")
        self.assertIn("Retry-After",response)

    @patch.object(ResearchSubmissionThrottle,"get_rate",return_value="1/hour")
    def test_expensive_submission_budget_does_not_block_reads(self, _rate):
        url="/api/v1/analysis/network-pharmacology/"
        self.assertEqual(self.client.post(url,{"herb":"NO_MATCH","disease":"NO_MATCH"},format="json").status_code,200)
        self.assertEqual(self.client.post(url,{"herb":"NO_MATCH","disease":"NO_MATCH"},format="json").status_code,429)
        self.assertEqual(self.client.get("/api/v1/research/analysis-tasks/").status_code,200)
