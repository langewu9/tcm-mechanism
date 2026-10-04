"""Offline contract checks for the configured local model; no real requests."""

import io
import json
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from apps.core.models import AnalysisTask, MedicalCase, MedicalCaseCandidate
from apps.core.services.case_analysis import CaseModelUnavailable, _local_model_response, case_input_sha256
from apps.core.services.research_assistant import _validated_model_text
from apps.core.tasks import run_case_analysis_task, run_research_assistant_task


MODEL_SETTINGS = {
    "CASE_MODEL_BASE_URL": "http://127.0.0.1:8000/v1",
    "CASE_MODEL_NAME": "fixture-local-model",
    "CASE_MODEL_VERSION": "fixture-model-v1",
    "CASE_MODEL_API_KEY": "fixture-key",
}


def response_bytes(content, *, finish_reason="stop", refusal=None):
    choice = {"message": {"content": json.dumps(content, ensure_ascii=False)}}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    if refusal is not None:
        choice["message"]["refusal"] = refusal
    return json.dumps({"choices": [choice]}, ensure_ascii=False).encode("utf-8")


@override_settings(**MODEL_SETTINGS)
class LocalModelConnectorContractTests(SimpleTestCase):
    def invoke(self, kind, body):
        module = "case_analysis" if kind == "case" else "research_assistant"
        with patch(f"apps.core.services.{module}.urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(body)
            if kind == "case":
                return _local_model_response({"deidentifiedText": "咳嗽"})
            return _validated_model_text("有哪些证据？", {"entities": [{"refId": "entity:7"}], "relations": []})[0]

    def test_completed_and_legacy_envelopes_remain_supported(self):
        for finish_reason in ("stop", None):
            with self.subTest(finish_reason=finish_reason):
                case_output = {"observations": [], "syndromeCandidates": [], "formulaCandidates": []}
                self.assertEqual(self.invoke("case", response_bytes(case_output, finish_reason=finish_reason)), case_output)
                result = self.invoke("assistant", response_bytes({
                    "answer": "记录证据不足。", "citations": ["entity:7", "made-up", "entity:7"], "uncertainties": []
                }, finish_reason=finish_reason))
                self.assertEqual(result["citations"], ["entity:7"])

    def test_explicitly_incomplete_or_refused_answers_are_never_accepted(self):
        answer = {"answer": "仍未完成的回答。", "citations": [], "uncertainties": []}
        for kind in ("case", "assistant"):
            for finish_reason in ("length", "content_filter", "tool_calls"):
                with self.subTest(kind=kind, reason=finish_reason):
                    with self.assertRaisesRegex(CaseModelUnavailable, "未完整完成"):
                        self.invoke(kind, response_bytes(answer, finish_reason=finish_reason))
            with self.subTest(kind=kind, refusal=True):
                with self.assertRaisesRegex(CaseModelUnavailable, "拒绝") as error:
                    self.invoke(kind, response_bytes(answer, refusal="PROVIDER_SECRET_DO_NOT_EXPOSE"))
                self.assertNotIn("PROVIDER_SECRET", str(error.exception))

    def test_malformed_envelopes_and_nonfinite_json_fail_with_safe_errors(self):
        payloads = [
            [], {}, {"choices": []}, {"choices": [None]}, {"choices": [{"message": []}]},
            {"choices": [{"message": {"content": []}}]},
            {"choices": [{"message": {"content": '{"answer": NaN}'}}]},
            {"choices": [{"message": {"content": '{"answer": Infinity}'}}]},
            {"choices": [{"message": {"content": '"MODEL_PRIVATE_RESPONSE"'}}]},
        ]
        for kind in ("case", "assistant"):
            for payload in payloads:
                with self.subTest(kind=kind, payload=payload):
                    with self.assertRaises(CaseModelUnavailable) as error:
                        self.invoke(kind, json.dumps(payload).encode())
                    self.assertNotIn("MODEL_PRIVATE_RESPONSE", str(error.exception))

    def test_assistant_rejects_missing_or_invalid_answer_schema(self):
        invalid_results = [
            {}, {"answer": "", "citations": [], "uncertainties": []},
            {"answer": "  ", "citations": [], "uncertainties": []},
            {"answer": ["文本"], "citations": [], "uncertainties": []},
            {"answer": "文本", "citations": "entity:7", "uncertainties": []},
            {"answer": "文本", "citations": [], "uncertainties": "待验证"},
        ]
        for result in invalid_results:
            with self.subTest(result=result):
                with self.assertRaisesRegex(CaseModelUnavailable, "缺少有效回答"):
                    self.invoke("assistant", response_bytes(result))

    def test_uncited_answer_keeps_explicit_evidence_warning(self):
        result = self.invoke("assistant", response_bytes({
            "answer": "尚无足够的本地记录。", "citations": ["unknown:99"], "uncertainties": []
        }))
        self.assertEqual(result["citations"], [])
        self.assertIn("没有给出可核验", result["uncertainties"][-1])

    def test_requests_still_bypass_proxy_and_refuse_redirects(self):
        for kind in ("case", "assistant"):
            module = "case_analysis" if kind == "case" else "research_assistant"
            with self.subTest(kind=kind), patch(f"apps.core.services.{module}.urllib.request.build_opener") as opener:
                opener.return_value.open.side_effect = HTTPError(
                    "http://127.0.0.1:8000/v1/chat/completions", 302, "redirect", {}, io.BytesIO(b"UPSTREAM_SECRET")
                )
                with self.assertRaises(CaseModelUnavailable) as error:
                    if kind == "case":
                        _local_model_response({"deidentifiedText": "咳嗽"})
                    else:
                        _validated_model_text("问题", {"entities": [], "relations": []})
                proxy_handler, redirect_handler = opener.call_args.args
                self.assertEqual(proxy_handler.proxies, {})
                self.assertIsNone(redirect_handler().redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid/"))
                self.assertNotIn("UPSTREAM_SECRET", str(error.exception))

    def test_response_size_limit_applies_to_both_model_paths(self):
        for kind in ("case", "assistant"):
            module = "case_analysis" if kind == "case" else "research_assistant"
            with self.subTest(kind=kind), patch(f"apps.core.services.{module}.MAX_MODEL_RESPONSE_BYTES", 128), patch(
                f"apps.core.services.{module}.urllib.request.build_opener"
            ) as opener:
                response = Mock()
                opener.return_value.open.return_value.__enter__.return_value = response
                response.read.return_value = b"x" * 129
                with self.assertRaisesRegex(CaseModelUnavailable, "大小限制"):
                    if kind == "case":
                        _local_model_response({"deidentifiedText": "咳嗽"})
                    else:
                        _validated_model_text("问题", {"entities": [], "relations": []})
                response.read.assert_called_once_with(129)


@override_settings(**MODEL_SETTINGS)
class ModelTaskFailureContractTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="offline-model-owner")

    @patch("apps.core.services.case_analysis.urllib.request.build_opener")
    def test_truncated_case_response_marks_task_failed_and_does_not_save_candidates(self, opener):
        case = MedicalCase.objects.create(owner=self.owner, title="合成医案", deidentified_text="患者咳嗽")
        task = AnalysisTask.objects.create(
            owner=self.owner, created_by=self.owner, medical_case=case, task_type=AnalysisTask.TaskType.CASE_LINK,
            input_parameters={"caseContentSha256": case_input_sha256(case), "localModelConsent": True},
        )
        opener.return_value.open.return_value = io.BytesIO(response_bytes({
            "observations": [{"type": "symptom", "value": "咳嗽", "evidence": [{"field": "deidentified_text", "quote": "咳嗽"}]}]
        }, finish_reason="length"))

        outcome = run_case_analysis_task.run(task.pk)

        task.refresh_from_db()
        self.assertEqual(outcome["status"], AnalysisTask.Status.FAILED)
        self.assertEqual(task.status, AnalysisTask.Status.FAILED)
        self.assertIn("未完整完成", task.error_summary)
        self.assertEqual(task.result, {})
        self.assertFalse(MedicalCaseCandidate.objects.filter(task=task).exists())

    @patch("apps.core.services.research_assistant.urllib.request.build_opener")
    def test_empty_assistant_response_marks_task_failed_instead_of_empty_success(self, opener):
        task = AnalysisTask.objects.create(
            owner=self.owner, created_by=self.owner, task_type=AnalysisTask.TaskType.RESEARCH_ASSISTANT,
            input_parameters={"question": "合成问题", "evidenceSnapshot": {"entities": [], "relations": []}, "useModel": True},
        )
        opener.return_value.open.return_value = io.BytesIO(response_bytes({}))

        outcome = run_research_assistant_task.run(task.pk)

        task.refresh_from_db()
        self.assertEqual(outcome["status"], AnalysisTask.Status.FAILED)
        self.assertIn("缺少有效回答", task.error_summary)
        self.assertEqual(task.result, {})
