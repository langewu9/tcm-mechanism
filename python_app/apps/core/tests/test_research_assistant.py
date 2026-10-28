import io
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease
from apps.core.services.research_assistant import (
    ResearchAssistantError,
    _validated_model_text,
    build_evidence_snapshot,
)
from apps.core.services.case_analysis import CaseModelUnavailable
from apps.core.tasks import run_research_assistant_task


class ResearchAssistantTests(APITestCase):
    databases = {"default", "case_rag"}
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="assistant-researcher", password="test-password-123"
        )
        enabled_source = DataSource.objects.create(
            slug="assistant-fixture", name="合成知识来源", enabled=True
        )
        self.release = SourceRelease.objects.create(source=enabled_source, version="fixture-v1")
        disabled_source = DataSource.objects.create(
            slug="assistant-disabled", name="停用来源", enabled=False
        )
        disabled_release = SourceRelease.objects.create(source=disabled_source, version="fixture-v1")
        self.herb = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.HERB,
            stable_id="herb:astragalus",
            label="黄芪",
            synonyms=["Astragalus"],
            source_release=self.release,
        )
        self.compound = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.COMPOUND,
            stable_id="compound:astragaloside-iv",
            label="黄芪甲苷",
            source_release=self.release,
        )
        self.target = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.GENE,
            stable_id="HGNC:11998",
            label="TP53",
            source_release=self.release,
        )
        self.inactive = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.HERB,
            stable_id="herb:inactive",
            label="停用中药",
            source_release=self.release,
            is_active=False,
        )
        self.disabled_entity = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.HERB,
            stable_id="herb:disabled-source",
            label="未启用来源中药",
            source_release=disabled_release,
        )
        self.edge = EvidenceRelation.objects.create(
            source_release=self.release,
            source_record_id="fixture-edge-1",
            subject=self.herb,
            object=self.compound,
            relation_type="contains_compound",
            evidence_type="database_record",
            evidence_text="合成测试记录：黄芪关联黄芪甲苷。",
        )
        EvidenceRelation.objects.create(
            source_release=disabled_release,
            source_record_id="disabled-edge",
            subject=self.herb,
            object=self.disabled_entity,
            relation_type="unverified_relation",
            evidence_type="fixture",
        )
        EvidenceRelation.objects.create(
            source_release=self.release,
            source_record_id="disabled-endpoint-edge",
            subject=self.herb,
            object=self.disabled_entity,
            relation_type="references_disabled_entity",
            evidence_type="fixture",
        )

    def test_snapshot_is_bounded_and_keeps_only_active_enabled_source_records(self):
        context, release_ids = build_evidence_snapshot([self.herb.pk, self.herb.pk])

        self.assertEqual(len(context["entities"]), 1)
        self.assertEqual(context["entities"][0]["sourceVersion"], "fixture-v1")
        self.assertEqual([row["refId"] for row in context["relations"]], [f"relation:{self.edge.pk}"])
        self.assertEqual(release_ids, [self.release.pk])

    def test_snapshot_refuses_inactive_or_disabled_entities(self):
        for selected in ([self.inactive.pk], [self.disabled_entity.pk]):
            with self.subTest(selected=selected), self.assertRaises(ResearchAssistantError):
                build_evidence_snapshot(selected)

    def test_catalog_and_neighborhood_hide_disabled_source_data(self):
        self.client.force_authenticate(self.user)

        entities = self.client.get(reverse("entity-list"))
        neighborhood = self.client.get(reverse("entity-neighborhood", args=[self.herb.pk]))
        relations = self.client.get(reverse("evidence-list"))

        self.assertEqual(entities.status_code, 200)
        self.assertNotIn(self.disabled_entity.pk, {item["id"] for item in entities.data["results"]})
        self.assertEqual(neighborhood.status_code, 200)
        self.assertEqual([item["id"] for item in neighborhood.data["relations"]], [self.edge.pk])
        self.assertEqual(relations.status_code, 200)
        self.assertEqual([item["id"] for item in relations.data["results"]], [self.edge.pk])

    @patch("apps.core.tasks.run_research_assistant_task.apply_async")
    def test_authenticated_submission_creates_owned_versioned_background_task(self, enqueue):
        self.client.force_authenticate(self.user)
        response = self.client.post(reverse("research-assistant"), {
            "question": "黄芪有哪些成分证据？",
            "entityIds": [self.herb.pk],
            "useModel": False,
        }, format="json")

        self.assertEqual(response.status_code, 202)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(task.owner, self.user)
        self.assertEqual(task.task_type, AnalysisTask.TaskType.RESEARCH_ASSISTANT)
        self.assertEqual(task.input_parameters["question"], "黄芪有哪些成分证据？")
        self.assertFalse(task.input_parameters["modelConsentRecorded"])
        self.assertEqual(list(task.source_releases.values_list("pk", flat=True)), [self.release.pk])
        self.assertEqual(task.input_parameters["evidenceSnapshot"]["relations"][0]["sourceRecordId"], "fixture-edge-1")
        enqueue.assert_called_once_with(args=[task.pk])

    def test_submission_requires_authentication_and_explicit_model_sharing_consent(self):
        payload = {"question": "分析关系", "entityIds": [self.herb.pk], "useModel": True}
        self.assertEqual(self.client.post(reverse("research-assistant"), payload, format="json").status_code, 401)
        self.client.force_authenticate(self.user)
        response = self.client.post(reverse("research-assistant"), payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AnalysisTask.objects.count(), 0)

    def test_researcher_cannot_read_another_users_assistant_task(self):
        other_user = get_user_model().objects.create_user(
            username="assistant-other-researcher", password="test-password-123"
        )
        task = AnalysisTask.objects.create(
            owner=self.user,
            task_type=AnalysisTask.TaskType.RESEARCH_ASSISTANT,
            input_parameters={"analysisKind": "research_assistant"},
        )
        self.client.force_authenticate(other_user)

        response = self.client.get(reverse("analysis-task-detail", args=[task.pk]))

        self.assertEqual(response.status_code, 404)

    def test_worker_local_catalog_mode_saves_evidence_without_calling_a_model(self):
        context, release_ids = build_evidence_snapshot([self.herb.pk])
        task = AnalysisTask.objects.create(
            owner=self.user,
            task_type=AnalysisTask.TaskType.RESEARCH_ASSISTANT,
            input_parameters={
                "question": "黄芪有哪些成分证据？",
                "evidenceSnapshot": context,
                "useModel": False,
            },
        )
        task.source_releases.set(release_ids)
        outcome = run_research_assistant_task.run(task.pk)

        self.assertEqual(outcome["status"], AnalysisTask.Status.SUCCEEDED)
        task.refresh_from_db()
        self.assertEqual(task.result["source"], "local_catalog_and_case_corpus")
        self.assertEqual(task.result["evidence"]["relations"][0]["sourceVersion"], "fixture-v1")
        self.assertIn("没有调用生成式模型", task.result["uncertainties"][0])

    @override_settings(
        CASE_MODEL_BASE_URL="http://127.0.0.1:8000/v1",
        CASE_MODEL_NAME="fixture-local-model",
        CASE_MODEL_VERSION="fixture-model-v1",
        CASE_MODEL_API_KEY="",
    )
    @patch("apps.core.services.research_assistant.urllib.request.build_opener")
    def test_model_result_citations_are_filtered_to_the_provided_evidence(self, build_opener):
        evidence = {
            "entities": [{"refId": "entity:7", "label": "黄芪", "sourceVersion": "v1"}],
            "relations": [{"refId": "relation:9", "subject": "黄芪", "object": "黄芪甲苷"}],
        }
        content = json.dumps({
            "answer": "本地记录提到黄芪甲苷。",
            "citations": ["entity:7", "relation:9", "relation:999", "made-up-ref"],
            "uncertainties": [],
        }, ensure_ascii=False)
        response_body = json.dumps({
            "choices": [{"message": {"content": content}}]
        }).encode("utf-8")
        build_opener.return_value.open.return_value = io.BytesIO(response_body)

        result, model = _validated_model_text("黄芪有哪些成分证据？", evidence)

        self.assertEqual(result["answer"], "本地记录提到黄芪甲苷。")
        self.assertEqual(result["citations"], ["entity:7", "relation:9"])
        self.assertEqual(model, {"name": "fixture-local-model", "version": "fixture-model-v1"})
        request = build_opener.return_value.open.call_args.args[0]
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request_body["model"], "fixture-local-model")
        self.assertIn("fixture-model-v1", str(model))
        self.assertNotIn("medicalCase", request_body["messages"][1]["content"])

    @override_settings(
        CASE_MODEL_BASE_URL="https://public-model.example/v1",
        CASE_MODEL_NAME="fixture-model",
        CASE_MODEL_VERSION="fixture-v1",
    )
    def test_model_call_refuses_public_hosts(self):
        with self.assertRaisesMessage(CaseModelUnavailable, "本机/内网"):
            _validated_model_text("问题", {"entities": [], "relations": []})
