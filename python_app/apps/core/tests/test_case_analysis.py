import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import (
    AnalysisTask,
    DataSource,
    EvidenceRelation,
    KnowledgeEntity,
    MedicalCase,
    MedicalCaseAuditEvent,
    MedicalCaseCandidate,
    SourceRelease,
)
from apps.core.services.case_analysis import (
    CaseAnalysisError,
    CaseModelUnavailable,
    _local_model_response,
    case_input_sha256,
    run_case_analysis,
)
from apps.core.tasks import run_case_analysis_task


class LocalCaseModelBoundaryTests(SimpleTestCase):
    @override_settings(CASE_MODEL_BASE_URL="https://api.openai.com/v1", CASE_MODEL_NAME="remote-model", CASE_MODEL_VERSION="v1")
    @patch("apps.core.services.case_analysis.urllib.request.build_opener")
    def test_public_model_endpoint_is_rejected_before_sending_case_data(self, build_opener):
        with self.assertRaisesRegex(CaseModelUnavailable, "本机或内网"):
            _local_model_response({"deidentifiedText": "不可发送"})
        build_opener.assert_not_called()

    @override_settings(CASE_MODEL_BASE_URL="http://169.254.169.254/latest", CASE_MODEL_NAME="local-model", CASE_MODEL_VERSION="v1")
    @patch("apps.core.services.case_analysis.urllib.request.build_opener")
    def test_link_local_metadata_address_is_not_an_allowed_model_endpoint(self, build_opener):
        with self.assertRaisesRegex(CaseModelUnavailable, "本机或内网"):
            _local_model_response({"deidentifiedText": "不可发送"})
        build_opener.assert_not_called()

    @override_settings(CASE_MODEL_BASE_URL="", CASE_MODEL_NAME="", CASE_MODEL_VERSION="")
    def test_missing_model_configuration_fails_closed(self):
        with self.assertRaisesRegex(CaseModelUnavailable, "尚未完整配置本地"):
            _local_model_response({"deidentifiedText": "咳嗽"})

    @override_settings(
        CASE_MODEL_BASE_URL="http://127.0.0.1:8000/v1",
        CASE_MODEL_NAME="local-model",
        CASE_MODEL_VERSION="v1",
        CASE_ANALYSIS_MAX_INPUT_CHARS=3,
    )
    def test_local_model_input_has_a_configured_character_limit(self):
        with self.assertRaisesRegex(CaseAnalysisError, "超过 3 个字符"):
            _local_model_response({"deidentifiedText": "超过限制"})


class MedicalCaseAnalysisWorkflowTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="case-analysis-owner", password="test-password-123")
        self.other = user_model.objects.create_user(username="case-analysis-other", password="test-password-123")
        self.case = MedicalCase.objects.create(
            owner=self.owner,
            title="去标识化医案",
            deidentified_text="患者咳嗽乏力，气短。",
            structured_data={"patient_info": "患者姓名绝不发送", "tongue_pulse": "舌淡，脉弱", "diagnosis": "慢性肺病"},
            source_reference="来源题名绝不发送",
            research_notes="研究备注绝不发送",
        )

    def make_task(self, *, status=AnalysisTask.Status.QUEUED):
        return AnalysisTask.objects.create(
            owner=self.owner,
            created_by=self.owner,
            task_type=AnalysisTask.TaskType.CASE_LINK,
            status=status,
            medical_case=self.case,
            input_parameters={
                "analysisKind": "case_analysis",
                "caseContentSha256": case_input_sha256(self.case),
                "localModelConsent": True,
            },
        )

    @override_settings(
        CASE_MODEL_BASE_URL="http://127.0.0.1:8000/v1",
        CASE_MODEL_NAME="fixture-local-model",
        CASE_MODEL_VERSION="fixture-v1",
    )
    @patch("apps.core.tasks.run_case_analysis_task.apply_async")
    def test_case_analysis_requires_explicit_local_model_confirmation_and_is_private(self, enqueue):
        self.client.force_authenticate(self.owner)
        rejected = self.client.post(
            reverse("case-analysis", args=[self.case.pk]),
            {"confirmLocalModel": False},
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(AnalysisTask.objects.count(), 0)

        response = self.client.post(
            reverse("case-analysis", args=[self.case.pk]),
            {"confirmLocalModel": True},
            format="json",
        )
        self.assertEqual(response.status_code, 202, response.data)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertTrue(task.input_parameters["localModelConsent"])
        self.assertEqual(task.input_parameters["caseContentSha256"], case_input_sha256(self.case))
        self.assertNotIn(self.case.deidentified_text, json.dumps(task.input_parameters, ensure_ascii=False))
        enqueue.assert_called_once_with(args=[task.pk])
        event = MedicalCaseAuditEvent.objects.get(action=MedicalCaseAuditEvent.Action.ANALYSIS_REQUESTED)
        self.assertNotIn(self.case.deidentified_text, json.dumps(event.metadata, ensure_ascii=False))
        duplicate = self.client.post(
            reverse("case-analysis", args=[self.case.pk]),
            {"confirmLocalModel": True},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 202)
        self.assertEqual(duplicate.data["id"], task.pk)
        self.assertEqual(MedicalCaseAuditEvent.objects.filter(action=MedicalCaseAuditEvent.Action.ANALYSIS_REQUESTED).count(), 1)

        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(reverse("case-analysis", args=[self.case.pk])).status_code, 404)

    @override_settings(CASE_MODEL_NAME="fixture-local-model", CASE_MODEL_VERSION="fixture-v1")
    @patch("apps.core.services.case_analysis._local_model_response")
    def test_worker_persists_only_verbatim_evidence_and_exact_local_entity_matches(self, model_response):
        syndrome = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.SYNDROME,
            stable_id="syndrome:lung-qi-deficiency",
            label="肺气虚",
            synonyms=["肺气虚证"],
        )
        model_response.return_value = {
            "observations": [
                {"type": "symptom", "value": "咳嗽", "evidence": [{"field": "deidentified_text", "quote": "患者咳嗽"}]},
                {"type": "symptom", "value": "胸痛", "evidence": [{"field": "deidentified_text", "quote": "胸痛"}]},
            ],
            "syndromeCandidates": [
                {"name": "肺气虚证", "confidence": 0.81, "evidence": [{"field": "deidentified_text", "quote": "乏力，气短"}]},
                {"name": "痰热壅肺", "confidence": 0.3, "evidence": [{"field": "deidentified_text", "quote": "无此原文"}]},
            ],
            "formulaCandidates": [],
        }
        task = self.make_task()

        outcome = run_case_analysis_task.run(task.pk)

        task.refresh_from_db()
        self.assertEqual(outcome["status"], AnalysisTask.Status.SUCCEEDED)
        self.assertEqual(task.result["model"], {
            "provider": "configured_local_openai_compatible",
            "name": "fixture-local-model",
            "version": "fixture-v1",
        })
        self.assertEqual(task.result["observations"], [{
            "type": "symptom",
            "value": "咳嗽",
            "evidence": [{"field": "deidentified_text", "quote": "患者咳嗽"}],
        }])
        candidate = MedicalCaseCandidate.objects.get(task=task)
        self.assertEqual(candidate.entity, syndrome)
        self.assertEqual(candidate.match_status, MedicalCaseCandidate.MatchStatus.EXACT)
        self.assertEqual(str(candidate.confidence), "0.8100")
        self.assertEqual(candidate.evidence[0]["quote"], "乏力，气短")
        self.assertEqual(task.result["evidenceChain"], {"nodes": [], "links": [], "sources": [], "truncated": False})
        model_response.assert_called_once_with({
            "deidentifiedText": self.case.deidentified_text,
            "tonguePulse": "舌淡，脉弱",
            "existingDiagnosis": "慢性肺病",
        })
        self.assertNotIn("患者姓名绝不发送", json.dumps(model_response.call_args.args[0], ensure_ascii=False))
        self.assertNotIn("来源题名绝不发送", json.dumps(model_response.call_args.args[0], ensure_ascii=False))
        self.assertNotIn("研究备注绝不发送", json.dumps(model_response.call_args.args[0], ensure_ascii=False))

    @patch("apps.core.services.case_analysis._local_model_response")
    def test_queued_analysis_is_rejected_if_medical_case_content_changed(self, model_response):
        task = self.make_task()
        self.case.deidentified_text += "后来加了新内容。"
        self.case.save(update_fields=["deidentified_text", "updated_at"])

        with self.assertRaisesRegex(CaseAnalysisError, "内容已修改"):
            run_case_analysis(task)
        model_response.assert_not_called()

    def test_candidate_review_requires_canonical_entity_and_builds_versioned_evidence_chain(self):
        source, _ = DataSource.objects.get_or_create(
            slug="case-analysis-test-source",
            defaults={"name": "病例研究证据测试源", "access_mode": DataSource.AccessMode.MANUAL},
        )
        release, _ = SourceRelease.objects.get_or_create(source=source, version="v1")
        syndrome = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.SYNDROME,
            stable_id="syndrome:lung-qi-deficiency",
            label="肺气虚",
            source_release=release,
        )
        formula = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.FORMULA,
            stable_id="formula:maimendong-tang",
            label="麦门冬汤",
            source_release=release,
        )
        herb = KnowledgeEntity.objects.create(entity_type=KnowledgeEntity.EntityType.HERB, stable_id="herb:mai-dong", label="麦冬")
        compound = KnowledgeEntity.objects.create(entity_type=KnowledgeEntity.EntityType.COMPOUND, stable_id="compound:baicalin", label="示例成分")
        gene = KnowledgeEntity.objects.create(entity_type=KnowledgeEntity.EntityType.GENE, stable_id="gene:tp53", label="TP53")
        pathway = KnowledgeEntity.objects.create(entity_type=KnowledgeEntity.EntityType.PATHWAY, stable_id="pathway:p53", label="p53 通路")
        relations = [
            (syndrome, formula, "syndrome_formula"),
            (formula, herb, "formula_herb"),
            (herb, compound, "herb_compound"),
            (compound, gene, "compound_gene"),
            (gene, pathway, "gene_pathway"),
        ]
        for index, (subject, object_, relation_type) in enumerate(relations):
            EvidenceRelation.objects.create(
                source_release=release,
                source_record_id=f"record-{index}",
                subject=subject,
                object=object_,
                relation_type=relation_type,
                evidence_type="curated",
                evidence_text=f"来源记录 {index}",
            )
        task = self.make_task(status=AnalysisTask.Status.SUCCEEDED)
        candidate = MedicalCaseCandidate.objects.create(
            task=task,
            medical_case=self.case,
            candidate_type=MedicalCaseCandidate.CandidateType.SYNDROME,
            label=syndrome.label,
            entity=syndrome,
            match_status=MedicalCaseCandidate.MatchStatus.EXACT,
            confidence="0.8100",
            rank=1,
            evidence=[{"field": "deidentified_text", "quote": "咳嗽"}],
        )
        unmatched = MedicalCaseCandidate.objects.create(
            task=task,
            medical_case=self.case,
            candidate_type=MedicalCaseCandidate.CandidateType.FORMULA,
            label="知识库未收录方剂",
            entity=None,
            match_status=MedicalCaseCandidate.MatchStatus.UNMATCHED,
            confidence="0.4200",
            rank=1,
            evidence=[{"field": "deidentified_text", "quote": "患者咳嗽"}],
        )
        self.client.force_authenticate(self.owner)

        original_text = self.case.deidentified_text
        self.case.deidentified_text += "后来补充了新症状。"
        self.case.save(update_fields=["deidentified_text", "updated_at"])
        stale_response = self.client.get(reverse("case-analysis", args=[self.case.pk]))
        self.assertTrue(stale_response.data["stale"])
        stale_accept = self.client.post(
            reverse("case-review-candidate", args=[self.case.pk, candidate.pk]),
            {"decision": "accept"},
            format="json",
        )
        self.assertEqual(stale_accept.status_code, 400)
        self.case.deidentified_text = original_text
        self.case.save(update_fields=["deidentified_text", "updated_at"])

        denied = self.client.post(
            reverse("case-review-candidate", args=[self.case.pk, unmatched.pk]),
            {"decision": "accept"},
            format="json",
        )
        self.assertEqual(denied.status_code, 400)

        response = self.client.post(
            reverse("case-review-candidate", args=[self.case.pk, candidate.pk]),
            {"decision": "accept", "note": "研究者确认"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["review_status"], MedicalCaseCandidate.ReviewStatus.ACCEPTED)
        task.refresh_from_db()
        self.assertEqual(len(task.result["evidenceChain"]["nodes"]), 6)
        self.assertEqual(len(task.result["evidenceChain"]["links"]), 5)
        self.assertEqual(task.result["evidenceChain"]["sources"][0]["version"], "v1")
        self.assertEqual(list(task.source_releases.all()), [release])
        event = MedicalCaseAuditEvent.objects.get(action=MedicalCaseAuditEvent.Action.CANDIDATE_REVIEWED)
        self.assertNotIn("咳嗽", json.dumps(event.metadata, ensure_ascii=False))
        self.assertNotIn("咳嗽", json.dumps(event.content_hashes, ensure_ascii=False))

        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(
            reverse("case-review-candidate", args=[self.case.pk, candidate.pk]),
            {"decision": "reject"},
            format="json",
        ).status_code, 404)

    @override_settings(CASE_MODEL_BASE_URL="https://api.openai.com/v1", CASE_MODEL_NAME="remote-model", CASE_MODEL_VERSION="v1")
    def test_public_model_configuration_is_not_disclosed_as_available_or_queued(self):
        self.client.force_authenticate(self.owner)
        state = self.client.get(reverse("case-analysis", args=[self.case.pk]))
        self.assertFalse(state.data["modelConfiguration"]["configured"])
        self.assertNotIn("baseUrl", state.data["modelConfiguration"])
        response = self.client.post(
            reverse("case-analysis", args=[self.case.pk]),
            {"confirmLocalModel": True},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AnalysisTask.objects.count(), 0)
