from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AnalysisTask, DataSource, SourceRelease


class TaskSummaryTests(TestCase):
    url = "/api/v1/research/analysis-tasks/summaries/"

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        user = get_user_model()
        self.owner = user.objects.create_user(username="summary-owner")
        self.other = user.objects.create_user(username="summary-other")
        self.admin = user.objects.create_user(username="summary-admin", is_superuser=True)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def task(self, **overrides):
        return AnalysisTask.objects.create(**{"owner": self.owner, "task_type": "network", **overrides})

    def test_summary_excludes_heavy_snapshots_and_bounds_display_fields(self):
        task = self.task(input_parameters={"name": "a" * 5000, "chartKey": "b" * 1000,
            "analysisKind": "c" * 1000, "parentTaskId": "42", "evidenceSnapshot": "PRIVATE_INPUT" * 20000},
            result={"evidence": "PRIVATE_RESULT" * 20000})
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(queries), 2)
        row = response.data["results"][0]
        self.assertEqual(row["id"], task.pk)
        for field in ("result", "input_parameters", "source_releases"):
            self.assertNotIn(field, row)
        self.assertEqual(len(row["display_parameters"]["name"]), 200)
        self.assertEqual(len(row["display_parameters"]["chartKey"]), 48)
        self.assertLess(len(response.content), 4000)
        self.assertNotIn(b"PRIVATE_", response.content)
        select_sql = next(query["sql"] for query in queries if "ORDER BY" in query["sql"])
        self.assertNotIn('"core_analysistask"."result"', select_sql)
        self.assertIn("no-store", response["Cache-Control"])

    def test_detail_and_original_list_keep_complete_historical_data(self):
        source = DataSource.objects.create(slug="summary-source", name="Synthetic source")
        release = SourceRelease.objects.create(source=source, version="test-v1")
        task = self.task(result={"private": [1, 2, 3]}, input_parameters={"evidenceSnapshot": [4, 5]})
        task.source_releases.add(release)
        for url in (f"/api/v1/research/analysis-tasks/{task.pk}/", "/api/v1/research/analysis-tasks/"):
            response = self.client.get(url)
            value = response.data["results"][0] if "results" in response.data else response.data
            self.assertEqual(value["result"], task.result)
            self.assertEqual(value["input_parameters"], task.input_parameters)
            self.assertEqual(value["source_releases"], [release.pk])

    def test_summary_requires_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_owner_scope_and_superuser_visibility_are_preserved(self):
        own = self.task()
        other = self.task(owner=self.other)
        response = self.client.get(self.url, {"owner": self.other.pk})
        self.assertEqual([item["id"] for item in response.data["results"]], [own.pk])
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.url).data["count"], 2)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get(f"/api/v1/research/analysis-tasks/{other.pk}/").status_code, 404)

    def test_parent_type_and_status_filters_work_on_summaries(self):
        parent = self.task()
        child = self.task(parent_task=parent, task_type="visualization", status="succeeded")
        self.task(task_type="visualization")
        response = self.client.get(self.url, {"parent_task": parent.pk, "task_type": "visualization", "status": "succeeded"})
        self.assertEqual([item["id"] for item in response.data["results"]], [child.pk])

    def test_tied_timestamps_have_stable_nonoverlapping_pages(self):
        tasks = [self.task() for _ in range(55)]
        AnalysisTask.objects.filter(pk__in=[task.pk for task in tasks]).update(created_at=timezone.now())
        first = self.client.get(self.url).data
        second = self.client.get(self.url, {"page": 2}).data
        ids = [row["id"] for row in first["results"] + second["results"]]
        self.assertEqual(ids, sorted([task.pk for task in tasks], reverse=True))
        self.assertIsNotNone(first["next"])
        self.assertIsNone(second["next"])

    def test_twenty_summaries_use_two_queries_without_source_prefetch(self):
        for _ in range(20):
            self.task()
        with self.assertNumQueries(2):
            response = self.client.get(self.url)
        self.assertEqual(len(response.data["results"]), 20)

    def test_summaries_are_read_only(self):
        self.assertEqual(self.client.post(self.url, {}, format="json").status_code, 405)
