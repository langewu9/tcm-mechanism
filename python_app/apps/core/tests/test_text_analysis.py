"""Behavior and private-data regression tests for the main text workbench port."""

import csv
import json
from io import StringIO

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import (
    AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, MedicalCase,
    MedicalCaseAuditEvent, SourceRelease,
)
from apps.core.services.case_analysis import case_input_sha256
from apps.core.services.text_analysis import build_text_analysis, create_text_analysis, rank_syndrome_rules
from apps.core.services.text_analysis_exports import export_text_analysis_csv, export_text_analysis_pdf


class TextAnalysisTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(username="text-owner", password="test-password-123")
        cls.other = user_model.objects.create_user(username="text-other", password="test-password-123")
        cls.admin = user_model.objects.create_superuser(
            username="text-admin", email="text-admin@example.test", password="test-password-123",
        )
        cls.source = DataSource.objects.create(slug="text-fixture", name="测试目录", access_mode="manual")
        cls.release = SourceRelease.objects.create(
            source=cls.source, version="fixture-v1", checksum_sha256="a" * 64,
        )
        cls.syndrome = cls.entity("syndrome", "syndrome:qixu", "气虚血瘀")
        cls.formula = cls.entity("formula", "formula:fixture", "测试方剂")
        cls.herb = cls.entity("herb", "herb:fixture", "测试中药")
        cls.compound = cls.entity("compound", "compound:fixture", "测试成分")
        cls.protein = cls.entity("protein", "protein:fixture", "测试蛋白")
        cls.gene = cls.entity("gene", "gene:fixture", "TEST_GENE")
        cls.pathway = cls.entity("pathway", "pathway:fixture", "测试通路")
        cls.edge_sf = cls.relation("syndrome_formula", cls.syndrome, cls.formula, "syndrome-formula")
        cls.edge_fh = cls.relation("formula_herb", cls.formula, cls.herb, "formula-herb")
        cls.relation("contains", cls.herb, cls.compound, "herb-compound")
        cls.relation("targets", cls.compound, cls.protein, "compound-protein")
        cls.relation("participatesin", cls.protein, cls.pathway, "protein-pathway")
        cls.relation("encoded_by", cls.protein, cls.gene, "protein-gene")
        cls.case = MedicalCase.objects.create(
            owner=cls.owner, title="自己的医案", deidentified_text="去标识化医案：乏力、舌暗",
            structured_data={"diagnosis": "科研原始记录"},
        )
        cls.other_case = MedicalCase.objects.create(
            owner=cls.other, title="其他研究者医案", deidentified_text="其他去标识化内容",
        )

    @classmethod
    def entity(cls, kind, stable_id, label, **kwargs):
        return KnowledgeEntity.objects.create(
            entity_type=kind, stable_id=stable_id, label=label,
            source_release=kwargs.pop("source_release", cls.release), **kwargs,
        )

    @classmethod
    def relation(cls, kind, subject, object_, record_id, **kwargs):
        return EvidenceRelation.objects.create(
            relation_type=kind, subject=subject, object=object_, source_record_id=record_id,
            source_release=kwargs.pop("source_release", cls.release), evidence_type="fixture", **kwargs,
        )

    def make_task(self, user=None, **kwargs):
        return create_text_analysis(
            user=user or self.owner, name=kwargs.pop("name", "文本规则分析"),
            query=kwargs.pop("query", "乏力、偏瘫、舌暗"), **kwargs,
        )

    def test_all_four_main_rules_count_distinct_keyword_hits_and_rank_stably(self):
        for text, name, keywords in (
            ("乏力、偏瘫、舌暗、脉涩、中风", "气虚血瘀", ["乏力", "偏瘫", "舌暗", "脉涩", "中风"]),
            ("痰、眩晕、麻木、语言不利、苔腻", "痰瘀阻络", ["痰", "眩晕", "麻木", "语言不利", "苔腻"]),
            ("头痛、眩晕、急躁、血压、肝阳", "肝阳上亢", ["头痛", "眩晕", "急躁", "血压", "肝阳"]),
            ("手足震颤、口干、失眠、舌红、风动", "阴虚风动", ["手足震颤", "口干", "失眠", "舌红", "风动"]),
        ):
            with self.subTest(name=name):
                ranked = rank_syndrome_rules(text)
                self.assertEqual(ranked[0], {"name": name, "score": 5, "matchedKeywords": keywords})
        tied = rank_syndrome_rules("眩晕、眩晕")
        self.assertEqual(tied[0]["name"], "痰瘀阻络")
        self.assertEqual(tied[1]["name"], "肝阳上亢")
        self.assertEqual(tied[0]["score"], 1)
        self.assertEqual(tied[1]["score"], 1)

    def test_no_keyword_match_never_uses_main_first_rule_or_first_catalogue_record(self):
        result = build_text_analysis("科研样本编号 A12")
        self.assertEqual(result["matchStatus"], "no_rule_match")
        self.assertIsNone(result["selectedRule"])
        self.assertEqual(result["evidence"]["syndrome"], "")
        self.assertEqual(result["evidence"]["formula"], [])
        self.assertEqual(result["network"], {"nodes": [], "links": []})
        self.assertEqual(result["sources"], [])
        missing = build_text_analysis("手足震颤、口干")
        self.assertEqual(missing["selectedRule"]["name"], "阴虚风动")
        self.assertEqual(missing["matchStatus"], "catalog_missing")
        self.assertEqual(missing["network"]["nodes"], [])

    def test_full_typed_chain_preserves_genes_and_versioned_relation_records(self):
        result = build_text_analysis("乏力、舌暗")
        self.assertEqual(result["matchStatus"], "matched")
        self.assertEqual(result["evidence"], {
            "syndrome": "气虚血瘀", "formula": ["测试方剂"], "herbs": ["测试中药"],
            "compounds": ["测试成分"], "targets": ["测试蛋白"], "genes": ["TEST_GENE"], "pathways": ["测试通路"],
        })
        records = result["evidenceRecords"]
        self.assertEqual(len(records), 6)
        self.assertEqual({record["sourceVersion"] for record in records}, {"fixture-v1"})
        self.assertEqual({record["sourceRecordId"] for record in records}, {
            "syndrome-formula", "formula-herb", "herb-compound", "compound-protein", "protein-pathway", "protein-gene",
        })
        self.assertEqual(result["sources"][0]["checksumSha256"], "a" * 64)
        ids = {node["id"] for node in result["network"]["nodes"]}
        self.assertIn("syndrome:syndrome:qixu", ids)
        self.assertIn("pathway:pathway:fixture", ids)
        self.assertTrue(all(link["source"] in ids and link["target"] in ids for link in result["network"]["links"]))

    def test_gene_targets_and_reverse_encodes_edges_are_included_without_duplicates(self):
        self.relation("targets", self.compound, self.gene, "compound-gene")
        self.relation("encodes", self.gene, self.protein, "gene-protein")
        result = build_text_analysis("乏力")
        self.assertEqual(set(result["evidence"]["targets"]), {"测试蛋白", "TEST_GENE"})
        self.assertEqual(result["evidence"]["genes"], ["TEST_GENE"])
        self.assertIn("gene-protein", {record["sourceRecordId"] for record in result["evidenceRecords"]})

    def test_inactive_entity_blocks_its_downstream_chain(self):
        self.herb.is_active = False
        self.herb.save(update_fields=["is_active"])
        result = build_text_analysis("乏力")
        self.assertEqual(result["evidence"]["formula"], ["测试方剂"])
        for field in ("herbs", "compounds", "targets", "genes", "pathways"):
            self.assertEqual(result["evidence"][field], [])
        self.assertEqual([item["sourceRecordId"] for item in result["evidenceRecords"]], ["syndrome-formula"])

    def test_inactive_relation_and_disabled_relation_source_do_not_leak_downstream_entities(self):
        self.edge_fh.is_active = False
        self.edge_fh.save(update_fields=["is_active"])
        hidden_source = DataSource.objects.create(slug="disabled-text", name="停用来源", enabled=False)
        hidden_release = SourceRelease.objects.create(source=hidden_source, version="hidden-v1")
        self.relation("formula_herb", self.formula, self.herb, "hidden-edge", source_release=hidden_release)
        result = build_text_analysis("乏力")
        self.assertEqual(result["evidence"]["herbs"], [])
        self.assertEqual(result["evidence"]["targets"], [])
        self.assertNotIn("hidden-edge", {item["sourceRecordId"] for item in result["evidenceRecords"]})
        self.assertNotIn("hidden-v1", {item["version"] for item in result["sources"]})

    def test_disabled_entity_source_and_syndrome_source_are_excluded(self):
        hidden_source = DataSource.objects.create(slug="hidden-entity-text", name="停用实体来源", enabled=False)
        hidden_release = SourceRelease.objects.create(source=hidden_source, version="hidden-v2")
        self.herb.source_release = hidden_release
        self.herb.save(update_fields=["source_release"])
        self.assertEqual(build_text_analysis("乏力")["evidence"]["herbs"], [])
        self.source.enabled = False
        self.source.save(update_fields=["enabled"])
        self.assertEqual(build_text_analysis("乏力")["matchStatus"], "catalog_missing")

    def test_same_label_syndromes_are_ambiguous_instead_of_arbitrarily_selected(self):
        self.entity("syndrome", "syndrome:second-source", "气虚血瘀")
        result = build_text_analysis("乏力")
        self.assertEqual(result["matchStatus"], "ambiguous_syndrome")
        self.assertEqual(result["network"], {"nodes": [], "links": []})
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["evidence"]["formula"], [])

    def test_relation_snapshot_has_a_global_500_record_cap_and_reports_truncation(self):
        EvidenceRelation.objects.bulk_create([
            EvidenceRelation(
                subject=self.syndrome, object=self.formula, source_release=self.release,
                relation_type="syndrome_formula", evidence_type="fixture", source_record_id=f"extra-formula-{index}",
            ) for index in range(500)
        ])
        result = build_text_analysis("乏力")
        self.assertEqual(len(result["evidenceRecords"]), 500)
        self.assertEqual(len(result["network"]["links"]), 500)
        self.assertTrue(result["limits"]["relationsTruncated"])
        self.assertEqual(result["limits"]["maxRelations"], 500)
        self.assertEqual(result["evidence"]["herbs"], [])
        self.assertTrue(any("500" in warning for warning in result["warnings"]))

    def legacy_rows(self):
        self.release.metadata = {"connector": "sqlite-herb-compound-target"}
        self.release.save(update_fields=["metadata"])
        for kind in ("contains", "targets"):
            EvidenceRelation.objects.filter(source_release=self.release, relation_type=kind).update(metadata={"sourceRowId": 1})

    def test_legacy_shared_compound_never_imports_another_herbs_target_or_pathway(self):
        self.legacy_rows()
        other_herb = self.entity("herb", "herb:unselected", "未选择的中药")
        foreign_target = self.entity("protein", "protein:unselected", "不属于本次中药的靶点")
        foreign_pathway = self.entity("pathway", "pathway:unselected", "不应进入结果的通路")
        self.relation("contains", other_herb, self.compound, "foreign-herb-row-2", metadata={"sourceRowId": 2})
        self.relation("targets", self.compound, foreign_target, "foreign-target-row-2", metadata={"sourceRowId": 2})
        self.relation("participatesin", foreign_target, foreign_pathway, "foreign-pathway")
        result = build_text_analysis("乏力")
        self.assertEqual(result["evidence"]["targets"], [self.protein.label])
        self.assertEqual(result["evidence"]["pathways"], [self.pathway.label])
        self.assertFalse({"foreign-target-row-2", "foreign-pathway"} & {row["sourceRecordId"] for row in result["evidenceRecords"]})

    def test_legacy_target_row_support_is_applied_before_the_remaining_cap(self):
        self.legacy_rows()
        EvidenceRelation.objects.filter(relation_type="targets").update(metadata={"sourceRowId": 2})
        for i in range(8):
            self.relation("targets", self.compound, self.gene, f"unselected-row-{i}", metadata={"sourceRowId": i + 10})
        valid = self.relation("targets", self.compound, self.protein, "selected-row-last", metadata={"sourceRowId": 1})
        result = build_text_analysis("乏力", relation_limit=4)
        self.assertEqual(result["evidence"]["targets"], [self.protein.label])
        self.assertIn(f"relation:{valid.pk}", {row["refId"] for row in result["evidenceRecords"]})
        self.assertEqual(len(result["evidenceRecords"]), 4)

    def test_legacy_missing_noninteger_or_cross_release_rows_do_not_establish_support(self):
        self.legacy_rows()
        second = SourceRelease.objects.create(source=self.source, version="other-row-v2", metadata=self.release.metadata)
        bad_rows = [{}, {"sourceRowId": "1"}, {"sourceRowId": True}, {"sourceRowId": 1.0}]
        for i, metadata in enumerate(bad_rows):
            self.relation("targets", self.compound, self.gene, f"invalid-row-{i}", metadata=metadata)
        self.relation("targets", self.compound, self.gene, "cross-release-row-1", metadata={"sourceRowId": 1}, source_release=second)
        result = build_text_analysis("乏力")
        self.assertEqual(result["evidence"]["targets"], [self.protein.label])
        self.assertNotIn("other-row-v2", {row["version"] for row in result["sources"]})

    def test_generic_compound_annotation_remains_valid_for_legacy_herb_chain(self):
        self.legacy_rows()
        source = DataSource.objects.create(slug="text-generic-annotation", name="显式的普通图关系")
        release = SourceRelease.objects.create(source=source, version="generic-v1")
        self.relation("compound_gene", self.compound, self.gene, "generic-gene", source_release=release)
        result = build_text_analysis("乏力")
        self.assertEqual(set(result["evidence"]["targets"]), {self.protein.label, self.gene.label})
        self.assertIn("generic-v1", {row["version"] for row in result["sources"]})

    def test_source_row_and_endpoint_identity_are_frozen_with_each_relation(self):
        self.legacy_rows()
        result = build_text_analysis("乏力")
        row = next(row for row in result["evidenceRecords"] if row["sourceRecordId"] == "compound-protein")
        self.assertEqual(row["sourceRowId"], 1)
        self.assertEqual(row["sourceReleaseId"], self.release.pk)
        self.assertEqual(row["sourceChecksumSha256"], "a" * 64)
        self.assertEqual(row["subjectStableId"], self.compound.stable_id)
        self.assertEqual(row["objectStableId"], self.protein.stable_id)

    def test_csv_reports_input_rule_status_and_incomplete_scope_without_hiding_warnings(self):
        task = self.make_task(query="科研编号，没有规则关键词")
        task.result["warnings"].append("合成截断提示")
        task.result["limits"]["relationsTruncated"] = True
        rows = list(csv.reader(StringIO(export_text_analysis_csv(task).decode("utf-8-sig"))))
        self.assertIn(["query", task.input_parameters["query"]], rows)
        self.assertIn(["match_status", "no_rule_match"], rows)
        self.assertIn(["warning", "合成截断提示"], rows)
        limits = json.loads(next(value for level, value in rows if level == "scope_limits"))
        self.assertTrue(limits["relationsTruncated"])

    def test_csv_chain_order_does_not_depend_on_database_json_key_order(self):
        task = self.make_task()
        task.result["evidence"] = dict(sorted(task.result["evidence"].items()))
        rows = list(csv.reader(StringIO(export_text_analysis_csv(task).decode("utf-8-sig"))))
        self.assertEqual([row[0] for row in rows[1:8]], ["syndrome", "formula", "herbs", "compounds", "targets", "genes", "pathways"])

    def test_task_and_source_snapshot_are_persisted_and_do_not_change_with_catalogue(self):
        task = self.make_task()
        self.assertEqual(task.owner, self.owner)
        self.assertEqual(task.created_by, self.owner)
        self.assertEqual(task.status, "succeeded")
        self.assertEqual(task.progress, 100)
        self.assertIsNotNone(task.started_at)
        self.assertIsNotNone(task.finished_at)
        self.assertEqual(list(task.source_releases.all()), [self.release])
        self.assertEqual(task.input_parameters["query"], "乏力、偏瘫、舌暗")
        self.assertEqual(task.input_parameters["algorithmVersion"], task.result["algorithmVersion"])
        self.assertEqual(task.input_parameters["ruleSource"], task.result["ruleSource"])
        original = task.result
        self.formula.label = "随后修改的目录名称"
        self.formula.save(update_fields=["label"])
        self.release.version = "later-v2"
        self.release.save(update_fields=["version"])
        self.edge_sf.is_active = False
        self.edge_sf.save(update_fields=["is_active"])
        task.refresh_from_db()
        self.assertEqual(task.result, original)
        self.assertEqual(task.result["evidence"]["formula"], ["测试方剂"])
        self.assertEqual(task.result["sources"][0]["version"], "fixture-v1")

    def test_snapshot_includes_entity_and_relation_releases_from_different_sources(self):
        source = DataSource.objects.create(slug="text-second", name="另一知识来源", access_mode="manual")
        release = SourceRelease.objects.create(source=source, version="second-v3", checksum_sha256="b" * 64)
        self.edge_fh.source_release = release
        self.edge_fh.save(update_fields=["source_release"])
        task = self.make_task()
        self.assertEqual(set(task.source_releases.values_list("pk", flat=True)), {self.release.pk, release.pk})
        snapshots = {item["sourceSlug"]: item for item in task.result["sources"]}
        self.assertEqual(snapshots["text-second"]["version"], "second-v3")
        self.assertEqual(snapshots["text-second"]["checksumSha256"], "b" * 64)
        record = next(item for item in task.result["evidenceRecords"] if item["sourceRecordId"] == "formula-herb")
        self.assertEqual(record["sourceSlug"], "text-second")
        self.assertEqual(record["sourceVersion"], "second-v3")

    def test_workspace_requires_login_and_validates_query_without_creating_tasks(self):
        url = reverse("text-analysis")
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.post(url, {"query": "乏力"}, format="json").status_code, 401)
        self.client.force_authenticate(self.owner)
        for payload in ({"query": " "}, {"query": "x" * 20001}, {"query": "乏力", "caseId": -1}):
            with self.subTest(payload_size=len(payload["query"])):
                response = self.client.post(url, payload, format="json")
                self.assertEqual(response.status_code, 400)
        self.assertEqual(AnalysisTask.objects.count(), 0)

    def test_binding_owned_case_records_owner_actor_hash_and_audit(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(reverse("text-analysis"), {
            "query": "乏力、舌暗", "name": "绑定医案分析", "caseId": self.case.pk,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(task.owner, self.owner)
        self.assertEqual(task.created_by, self.owner)
        self.assertEqual(task.medical_case, self.case)
        self.assertEqual(task.input_parameters["caseInputSha256"], case_input_sha256(self.case))
        audit = MedicalCaseAuditEvent.objects.get(case=self.case, action="analyzed")
        self.assertEqual(audit.actor, self.owner)
        self.assertEqual(audit.metadata["taskId"], task.pk)

    def test_binding_other_users_case_is_hidden_but_platform_admin_preserves_case_owner(self):
        self.client.force_authenticate(self.owner)
        for case_id in (self.other_case.pk, 999999):
            response = self.client.post(reverse("text-analysis"), {"query": "乏力", "caseId": case_id}, format="json")
            self.assertEqual(response.status_code, 404)
        self.assertEqual(AnalysisTask.objects.count(), 0)
        self.client.force_authenticate(self.admin)
        response = self.client.post(reverse("text-analysis"), {"query": "乏力", "caseId": self.other_case.pk}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        task = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(task.owner, self.other)
        self.assertEqual(task.created_by, self.admin)
        self.assertEqual(task.medical_case, self.other_case)

    def test_workspace_recent_eight_text_tasks_and_cases_are_isolated_by_owner(self):
        own = [self.make_task(name=f"自有分析 {index}") for index in range(10)]
        other_task = self.make_task(user=self.other, name="他人文本分析")
        AnalysisTask.objects.create(owner=self.owner, task_type="network", result={"private": "not text"})
        self.client.force_authenticate(self.owner)
        response = self.client.get(reverse("text-analysis"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["tasks"]], [task.pk for task in own[-8:][::-1]])
        self.assertEqual([item["id"] for item in response.data["cases"]], [self.case.pk])
        self.assertFalse(response.data["casesTruncated"])
        self.client.force_authenticate(self.admin)
        admin_response = self.client.get(reverse("text-analysis"))
        self.assertEqual(len(admin_response.data["tasks"]), 8)
        self.assertEqual(admin_response.data["tasks"][0]["id"], other_task.pk)
        self.assertEqual({item["id"] for item in admin_response.data["cases"]}, {self.case.pk, self.other_case.pk})

    def test_workspace_limits_case_options_to_latest_200_without_other_owner_leakage(self):
        MedicalCase.objects.bulk_create([
            MedicalCase(owner=self.owner, title=f"自有医案 {index}", deidentified_text="去标识化测试文本")
            for index in range(201)
        ])
        self.client.force_authenticate(self.owner)
        response = self.client.get(reverse("text-analysis"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["cases"]), 200)
        self.assertTrue(response.data["casesTruncated"])
        visible = {item["id"] for item in response.data["cases"]}
        self.assertNotIn(self.other_case.pk, visible)
        self.assertNotIn(self.case.pk, visible)

    def test_exports_require_owner_or_platform_admin_and_reject_wrong_formats_or_pending_tasks(self):
        task = self.make_task()
        url = reverse("analysis-task-export", args=[task.pk])
        self.assertEqual(self.client.get(url).status_code, 401)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url + "?file_format=csv").status_code, 404)
        self.assertEqual(self.client.get(url + "?file_format=pdf").status_code, 404)
        self.client.force_authenticate(self.owner)
        csv_response = self.client.get(url + "?file_format=csv")
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("text/csv", csv_response["Content-Type"])
        self.assertEqual(csv_response["X-Content-Type-Options"], "nosniff")
        self.assertIn(f"text-analysis-task-{task.pk}.csv", csv_response["Content-Disposition"])
        self.assertIn("气虚血瘀", csv_response.content.decode("utf-8-sig"))
        self.assertEqual(self.client.get(url + "?file_format=xlsx").status_code, 400)
        self.client.force_authenticate(self.admin)
        pdf_response = self.client.get(url + "?file_format=pdf")
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")
        self.assertTrue(pdf_response.content.startswith(b"%PDF-"))
        self.assertIn(f"text-analysis-task-{task.pk}.pdf", pdf_response["Content-Disposition"])
        task.status = "queued"
        task.save(update_fields=["status"])
        self.assertEqual(self.client.get(url + "?file_format=pdf").status_code, 404)

    def test_csv_export_escapes_formula_strings_and_preserves_source_snapshot(self):
        task = self.make_task()
        payloads = {"syndrome": " =HYPERLINK(\"https://invalid\")", "formula": ["+SUM(1,2)"],
                    "herbs": ["-ABC"], "compounds": ["@A1"], "targets": ["\tTARGET"],
                    "genes": ["\rGENE"], "pathways": ["\n通路\"名称"]}
        task.result["evidence"] = payloads
        rows = list(csv.reader(StringIO(export_text_analysis_csv(task).decode("utf-8-sig"))))
        parsed = dict(rows[:8])
        self.assertEqual(parsed["syndrome"], "'" + payloads["syndrome"])
        for level in ("formula", "herbs", "compounds", "targets", "genes", "pathways"):
            self.assertEqual(parsed[level], "'" + payloads[level][0])
        self.assertTrue(any(level == "source" and "fixture-v1" in value and "a" * 64 in value for level, value in rows[1:]))
        self.assertTrue(any(level == "relation_evidence" and "syndrome-formula" in value for level, value in rows[1:]))

    def test_pdf_has_chinese_font_and_a_valid_page_tree_even_with_escaped_markup(self):
        task = self.make_task(name="中文科研报告 <标题>")
        task.result["summary"] += " <script> & 标题字段仅作文本展示。"
        payload = export_text_analysis_pdf(task)
        self.assertTrue(payload.startswith(b"%PDF-"))
        self.assertIn(b"/STSong-Light", payload)
        self.assertIn(b"/Type /Pages", payload)
        self.assertTrue(payload.rstrip().endswith(b"%%EOF"))

    def test_cookie_authenticated_creation_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        url = reverse("text-analysis")
        payload = {"query": "乏力", "name": "CSRF验证"}
        rejected = client.post(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(rejected.json()["error"]["code"], "CSRF_FAILED")
        self.assertEqual(AnalysisTask.objects.count(), 0)
        token = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        accepted = client.post(url, json.dumps(payload), content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(AnalysisTask.objects.get(pk=accepted.json()["id"]).owner, self.owner)
