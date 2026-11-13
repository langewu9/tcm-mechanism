import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase
from apps.case_rag.models import CaseCorpusDocument, RagCorpusRelease
from apps.case_rag.services import CaseCorpusUnavailable, build_case_snapshot, query_terms
from apps.case_rag.management.commands.import_case_rag import _make_document
from apps.case_rag.management.commands.extend_case_rag import make_general_document
from django.core.management import call_command
from django.core.management.base import CommandError
from apps.case_rag.services import active_release, serialize_document
from apps.core.models import AnalysisTask, MedicalCase, SensitiveAccessEvent
from apps.core.services.case_analysis import case_input_sha256, run_case_analysis
from apps.core.services.research_assistant import _validated_model_text, build_evidence_snapshot, run_research_assistant
from django.test import override_settings


class CaseCorpusTests(APITestCase):
    databases = {"default", "case_rag"}

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="case-library-test", password="test-password")
        self.release = RagCorpusRelease.objects.using("case_rag").create(
            name="合成测试医案集", version="test-v1", workbook_name="test.xlsx", checksum_sha256="a" * 64,
            record_count=len(CaseCorpusDocument.Category.choices),
        )
        self.documents = []
        for category, label in CaseCorpusDocument.Category.choices:
            self.documents.append(self.make_document(category, category, f"{label} 合成医案", f"{label} 咳嗽 舌红"))

    def make_document(self, key, category="pulmonary", title="合成医案", text="咳嗽"):
        return CaseCorpusDocument.objects.using("case_rag").create(
            release=self.release, source_record_id=key, source_sheet=category,
            category=category, title=title, original_text=text, search_text=text,
            structured_data={"主诉": text, "舌象": "舌红"}, source_reference="合成出处",
            extraction_status="合成测试，待核验", content_sha256="b" * 64,
        )

    def authenticate(self):
        self.client.force_authenticate(self.user)

    def test_library_requires_login_and_is_read_only(self):
        self.assertEqual(self.client.get(reverse("case-corpus-list")).status_code, 401)
        self.assertEqual(self.client.get(reverse("case-corpus-detail", args=[self.documents[0].pk])).status_code, 401)
        self.authenticate()
        self.assertEqual(self.client.post(reverse("case-corpus-list"), {}, format="json").status_code, 405)
        self.assertEqual(self.client.delete(reverse("case-corpus-detail", args=[self.documents[0].pk])).status_code, 405)

    def test_list_counts_categories_and_has_bounded_page(self):
        self.authenticate()
        response = self.client.get(reverse("case-corpus-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], len(CaseCorpusDocument.Category.choices))
        self.assertEqual(sum(row["count"] for row in response.data["summary"]["categories"]), len(CaseCorpusDocument.Category.choices))
        self.assertNotIn("originalText", response.data["results"][0])
        self.assertNotIn("search_text", response.data["results"][0])
        event = SensitiveAccessEvent.objects.get(operation="case_corpus.list")
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.action, "list")
        self.assertEqual(event.resources, [
            {"type": "case_corpus_document", "id": row["id"],
             "ownerId": None, "releaseId": self.release.pk}
            for row in response.data["results"]
        ])
        self.assertNotIn("originalText", str(event.resources))

    def test_category_and_query_filter_and_empty_page(self):
        self.authenticate()
        response = self.client.get(reverse("case-corpus-list"), {"category": "stroke", "q": "中风"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["category"], "stroke")
        response = self.client.get(reverse("case-corpus-list"), {"page": 2})
        self.assertEqual(response.data["results"], [])
        for params in ({"page": 0}, {"category": "invented"}, {"q": "x" * 161}):
            self.assertEqual(self.client.get(reverse("case-corpus-list"), params).status_code, 400)

    @patch("apps.core.tasks.run_research_assistant_task.apply_async")
    def test_general_cases_support_strict_scope_and_automatic_disease_recall(self, enqueue):
        self.authenticate()
        general = self.documents[-1]
        response = self.client.get(reverse("case-corpus-list"), {"category": "general"})
        self.assertEqual([row["id"] for row in response.data["results"]], [general.pk])
        snapshot = build_case_snapshot("咳嗽 咳痰")
        self.assertIn(general.pk, [row["id"] for row in snapshot["documents"]])
        response = self.client.post(reverse("research-assistant"), {"question": "咳嗽", "entityIds": [], "caseCategory": "general"}, format="json")
        self.assertEqual(response.status_code, 202)
        frozen = AnalysisTask.objects.get(pk=response.data["id"]).input_parameters["evidenceSnapshot"]
        self.assertEqual([row["category"] for row in frozen["cases"]], ["general"])

    def test_detail_returns_original_and_provenance_without_private_cases(self):
        self.authenticate()
        private = MedicalCase.objects.create(owner=self.user, title="PRIVATE-ONLY", deidentified_text="私有医案标记")
        response = self.client.get(reverse("case-corpus-detail", args=[self.documents[0].pk]))
        self.assertEqual(response.data["originalText"], self.documents[0].original_text)
        self.assertEqual(response.data["sourceVersion"], "test-v1")
        self.assertEqual(response.data["contentSha256"], "b" * 64)
        self.assertNotIn(private.deidentified_text, json.dumps(response.data, ensure_ascii=False))
        event = SensitiveAccessEvent.objects.get(operation="case_corpus.detail")
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.action, "view")
        self.assertEqual(event.resources, [{
            "type": "case_corpus_document", "id": self.documents[0].pk,
            "ownerId": None, "releaseId": self.release.pk,
        }])
        self.assertNotIn(self.documents[0].original_text, json.dumps(event.resources, ensure_ascii=False))

    def test_inactive_release_not_browsable_or_selectable(self):
        self.release.is_active = False
        self.release.save(using="case_rag")
        self.authenticate()
        self.assertEqual(self.client.get(reverse("case-corpus-detail", args=[self.documents[0].pk])).status_code, 404)
        self.assertFalse(self.client.get(reverse("case-corpus-list")).data["summary"]["available"])
        with self.assertRaises(CaseCorpusUnavailable):
            build_case_snapshot("咳嗽", [self.documents[0].pk])

    def test_chinese_long_query_keeps_clinical_terms(self):
        terms = query_terms("请帮我检索存在咳嗽咳痰伴有喘息表现的相关医案并整理来源")
        self.assertIn("咳嗽", terms)
        self.assertIn("咳痰", terms)
        self.assertLessEqual(len(terms), 18)

    def test_numeric_record_number_prefers_exact_identifier_over_body_text(self):
        self.authenticate()
        target = self.make_document("linglan:0001", "general", text="合成医案甲")
        self.make_document("linglan:1001", "general", text="正文出现数字 0001 的另一医案")
        for question in ("0001", "linglan:0001"):
            response = self.client.get(reverse("case-corpus-list"), {"q": question, "category": "general"})
            self.assertEqual([row["id"] for row in response.data["results"]], [target.pk])
            snapshot = build_case_snapshot(question)
            self.assertEqual([row["id"] for row in snapshot["documents"]], [target.pk])

    def test_prefilled_library_question_retrieves_its_category(self):
        record = self.make_document("pulmonary-caption", text="肺系疾病 咳嗽")
        snapshot = build_case_snapshot("请整理这份肺系疾病参考医案的症状、证型与方药记录，并注明原文依据和不确定性。")
        self.assertGreater(snapshot["matchedCount"], 0)
        self.assertIn(record.pk, [document["id"] for document in snapshot["documents"]])

    def test_rank_applies_to_all_matches_before_limit(self):
        CaseCorpusDocument.objects.using("case_rag").bulk_create([
            CaseCorpusDocument(release=self.release, source_record_id=f"early-{index:04}", source_sheet="肺系", category="pulmonary",
                               title="合成早序记录", original_text="咳嗽", search_text="咳嗽", content_sha256="c" * 64)
            for index in range(400)
        ])
        late = self.make_document("zzz-late", text="咳嗽 咳痰 喘息 哮喘")
        snapshot = build_case_snapshot("咳嗽 咳痰 喘息 哮喘")
        self.assertEqual(snapshot["documents"][0]["id"], late.pk)
        self.assertEqual(len(snapshot["documents"]), 4)
        self.assertTrue(snapshot["truncated"])

    def test_selected_record_survives_automatic_retrieval(self):
        selected = self.documents[-1]
        snapshot = build_case_snapshot("咳嗽", [selected.pk])
        self.assertEqual(snapshot["documents"][0]["id"], selected.pk)
        self.assertTrue(snapshot["documents"][0]["selected"])
        with self.assertRaises(CaseCorpusUnavailable):
            build_case_snapshot("咳嗽", [999999])

    @patch("apps.core.tasks.run_research_assistant_task.apply_async")
    def test_assistant_empty_entity_selection_freezes_case_snapshot(self, enqueue):
        self.authenticate()
        response = self.client.post(reverse("research-assistant"), {"question": "咳嗽", "entityIds": [], "caseIds": [self.documents[0].pk]}, format="json")
        self.assertEqual(response.status_code, 202)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.release.is_active = False
        self.release.save(using="case_rag")
        with patch("apps.core.services.research_assistant._validated_model_text") as model:
            result = run_research_assistant(task)
        model.assert_not_called()
        self.assertEqual(result["evidence"]["caseCorpus"]["version"], "test-v1")
        self.assertEqual(result["evidence"]["cases"][0]["id"], self.documents[0].pk)
        enqueue.assert_called_once()

    @override_settings(CASE_MODEL_BASE_URL="", CASE_MODEL_NAME="", CASE_MODEL_VERSION="")
    def test_unconfigured_model_does_not_create_a_false_model_task(self):
        self.authenticate()
        response = self.client.post(reverse("research-assistant"), {"question": "咳嗽", "entityIds": [], "useModel": True, "confirmModelSharing": True}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AnalysisTask.objects.count(), 0)
        summary = self.client.get(reverse("case-corpus-summary"))
        self.assertFalse(summary.data["modelConfiguration"]["configured"])
        self.assertNotIn("baseUrl", summary.data["modelConfiguration"])

    @patch("apps.core.services.case_analysis._local_model_response")
    def test_personal_case_rag_uses_frozen_reference_and_verbatim_patient_evidence(self, model):
        case = MedicalCase.objects.create(owner=self.user, title="合成测试", deidentified_text="患者咳嗽。")
        snapshot = build_case_snapshot("咳嗽", [self.documents[0].pk])
        # Direct service execution simulates a task already claimed by a worker.
        task = AnalysisTask.objects.create(owner=self.user, task_type="case_link", medical_case=case,
            status=AnalysisTask.Status.RUNNING,
            input_parameters={"caseContentSha256": case_input_sha256(case), "caseCorpusSnapshot": snapshot})
        self.release.is_active = False
        self.release.save(using="case_rag")
        model.return_value = {"observations": [{"type": "symptom", "value": "咳嗽", "evidence": [{"field": "deidentified_text", "quote": "患者咳嗽。"}]}]}
        result = run_case_analysis(task)
        self.assertEqual(result["retrievalContext"]["cases"][0]["id"], self.documents[0].pk)
        self.assertEqual(model.call_args.args[1]["caseCorpus"]["version"], "test-v1")
        self.assertEqual(result["observations"][0]["evidence"][0]["quote"], "患者咳嗽。")

    def test_stomach_import_excludes_identity_and_account_columns(self):
        headers = ["编号", "主诉", "姓名", "姓名缩写", "病例号", "账户", "样本号"]
        payload = _make_document("胃病", CaseCorpusDocument.Category.STOMACH, 2, headers,
                                 ["demo", "胃痛", "PRIVATE-NAME", "PRIVATE-INITIALS", "PRIVATE-ID", "PRIVATE-ACCOUNT", "PRIVATE-SAMPLE"])
        self.assertNotIn("PRIVATE-", json.dumps(payload, ensure_ascii=False))

    def test_general_import_preserves_missing_complaint_original_and_source(self):
        headers = ["编号", "医家", "主诉", "主诉标注情况", "病历文本", "辨证", "治法", "处方", "姓名"]
        payload = make_general_document(headers, ["1", "合成医家", "", "原文无主诉标注", "合成原案咳嗽", "气虚", "益气", "合成方", "PRIVATE-NAME"], 2, "linglan.xlsx", "d" * 64)
        self.assertIsNone(payload["structured_data"]["主诉"])
        self.assertEqual(payload["structured_data"]["主诉标注情况"], "原文无主诉标注")
        self.assertEqual(payload["original_text"], "合成原案咳嗽")
        self.assertEqual(payload["source_record_id"], "linglan:1")
        self.assertNotIn("PRIVATE-NAME", json.dumps(payload, ensure_ascii=False))
        document = CaseCorpusDocument.objects.using("case_rag").create(release=self.release, **payload)
        detail = serialize_document(document, detail=True)
        self.assertEqual(detail["workbookName"], "linglan.xlsx")
        self.assertEqual(detail["sourceChecksumSha256"], "d" * 64)

    def run_general_import(self, rows, path, **options):
        headers = ["编号", "医家", "主诉", "主诉标注情况", "病历文本", "辨证", "治法", "处方"]
        sheet = SimpleNamespace(iter_rows=lambda **kwargs: iter([headers, *rows]))

        class Workbook:
            sheetnames = ["医家案例2000例"]
            def __getitem__(self, key):
                return sheet
            def close(self):
                pass

        output = io.StringIO()
        with patch("openpyxl.load_workbook", return_value=Workbook()):
            call_command("extend_case_rag", str(path), expected_source_count=2,
                         expected_total=self.release.record_count + 2, stdout=output, **options)
        return json.loads(output.getvalue())

    def test_merge_is_atomic_versioned_and_idempotent(self):
        rows = [[str(i), "合成医家", "咳嗽", "主诉：标注", f"合成原案 {i}", "气虚", "益气", "合成方"] for i in (1, 2)]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.xlsx"
            path.write_bytes(b"synthetic-import-fixture")
            preview = self.run_general_import(rows, path, dry_run=True)
            self.assertEqual(preview["addedCount"], 2)
            self.assertEqual(RagCorpusRelease.objects.using("case_rag").count(), 1)
            result = self.run_general_import(rows, path)
            current = active_release()
            self.assertEqual(current.pk, result["releaseId"])
            self.assertEqual(current.record_count, len(CaseCorpusDocument.Category.choices) + 2)
            self.release.refresh_from_db(using="case_rag")
            self.assertFalse(self.release.is_active)
            self.assertEqual(self.release.documents.count(), len(CaseCorpusDocument.Category.choices))
            copied = current.documents.get(source_record_id=self.documents[0].source_record_id)
            self.assertEqual(copied.content_sha256, self.documents[0].content_sha256)
            self.assertEqual(copied.source_workbook, "test.xlsx")
            self.assertEqual(copied.source_workbook_sha256, "a" * 64)
            again = self.run_general_import(rows, path)
            self.assertTrue(again["alreadyImported"])
            self.assertEqual(again["addedCount"], 0)
            self.assertEqual(again["releaseId"], current.pk)
            self.assertEqual(RagCorpusRelease.objects.using("case_rag").count(), 2)

    def test_duplicate_source_numbers_leave_active_corpus_unchanged(self):
        rows = [["1", "合成医家", "咳嗽", "主诉：标注", "合成原案", "气虚", "益气", "合成方"]] * 2
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.xlsx"
            path.write_bytes(b"synthetic-import-fixture")
            with self.assertRaises(CommandError):
                self.run_general_import(rows, path)
        self.assertEqual(active_release().pk, self.release.pk)
        self.assertEqual(RagCorpusRelease.objects.using("case_rag").count(), 1)

    @override_settings(CASE_MODEL_BASE_URL="http://127.0.0.1:8000/v1", CASE_MODEL_NAME="fixture", CASE_MODEL_VERSION="fixture-v1")
    @patch("apps.core.services.research_assistant.urllib.request.build_opener")
    def test_model_case_citations_are_checked_against_sent_records(self, opener):
        opener.return_value.open.return_value = io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps({"answer": "合成说明", "citations": ["case:1", "case:999"], "uncertainties": []})}}]}).encode())
        generated, _ = _validated_model_text("咳嗽", {"cases": [{"refId": "case:1", "originalExcerpt": "合成原案"}]})
        self.assertEqual(generated["citations"], ["case:1"])
