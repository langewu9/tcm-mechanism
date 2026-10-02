from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, MedicalCase, MedicalCaseCandidate, SourceRelease
from apps.core.services.case_analysis import case_input_sha256


class NetworkPharmacologyApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="network-owner", password="test-password-123")
        self.other = user_model.objects.create_user(username="network-other", password="test-password-123")
        self.source = DataSource.objects.create(slug="fixture", name="合成测试来源")
        self.release = SourceRelease.objects.create(
            source=self.source, version="fixture-v1", checksum_sha256="f" * 64,
        )
        self.herb = self.entity(KnowledgeEntity.EntityType.HERB, "herb:huangqin", "黄芩")
        self.compound = self.entity(KnowledgeEntity.EntityType.COMPOUND, "compound:baicalin", "黄芩苷")
        self.tp53 = self.entity(KnowledgeEntity.EntityType.PROTEIN, "protein:tp53", "TP53", {"symbol": "TP53"})
        self.akt1 = self.entity(KnowledgeEntity.EntityType.PROTEIN, "protein:akt1", "AKT1", {"symbol": "AKT1"})
        self.disease = self.entity(KnowledgeEntity.EntityType.DISEASE, "disease:fibrosis", "肺纤维化")
        self.pathway = self.entity(KnowledgeEntity.EntityType.PATHWAY, "R-HSA-123", "细胞应激响应")
        self.relation("contains", self.herb, self.compound, "hct:1")
        self.relation("targets", self.compound, self.tp53, "hct:2")
        self.relation("disease_target", self.disease, self.tp53, "dt:1")
        self.relation("disease_target", self.disease, self.akt1, "dt:2")
        self.relation(
            "disease_herb_target", self.disease, self.akt1, "dht:1",
            metadata={"herbStableId": self.herb.stable_id, "herbLabel": self.herb.label},
        )
        self.relation("participatesin", self.tp53, self.pathway, "path:1")

    def entity(self, entity_type, stable_id, label, metadata=None):
        return KnowledgeEntity.objects.create(
            entity_type=entity_type, stable_id=stable_id, label=label, metadata=metadata or {},
            source_release=self.release,
        )

    def relation(self, kind, subject, object_, record_id, metadata=None):
        return EvidenceRelation.objects.create(
            source_release=self.release, source_record_id=record_id, subject=subject, object=object_,
            relation_type=kind, evidence_type="fixture", metadata=metadata or {},
        )

    def test_requires_authentication_and_limits_herb_count(self):
        response = self.client.post(
            reverse("network-pharmacology"), {"herb": "黄芩", "disease": "肺纤维化"}, format="json"
        )
        self.assertEqual(response.status_code, 401)

        self.client.force_authenticate(self.owner)
        too_many = self.client.post(
            reverse("network-pharmacology"),
            {"herb": "".join(f"药{i}、" for i in range(13)), "disease": "肺纤维化"},
            format="json",
        )
        self.assertEqual(too_many.status_code, 400)

    def test_returns_local_evidence_intersection_and_records_private_task(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            reverse("network-pharmacology"),
            {"herb": "黄芩", "disease": "肺纤维化"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["herbTargetCount"], 1)
        self.assertEqual(response.data["summary"]["diseaseTargetCount"], 2)
        self.assertEqual(response.data["summary"]["strictIntersectionCount"], 1)
        self.assertEqual(response.data["summary"]["directAssociationTargetCount"], 1)
        self.assertEqual({item["target"] for item in response.data["targets"]}, {"TP53", "AKT1"})
        tp53 = next(item for item in response.data["targets"] if item["target"] == "TP53")
        self.assertEqual(tp53["pathways"], ["细胞应激响应"])
        self.assertEqual(tp53["sources"][0]["sourceVersion"], "fixture-v1")
        task = AnalysisTask.objects.get(pk=response.data["taskId"])
        self.assertEqual(task.owner, self.owner)
        self.assertEqual(task.status, AnalysisTask.Status.SUCCEEDED)
        self.assertEqual(list(task.source_releases.all()), [self.release])

        self.client.force_authenticate(self.other)
        task_response = self.client.get(reverse("analysis-task-detail", args=[task.pk]))
        self.assertEqual(task_response.status_code, 404)

    def test_unknown_entities_return_an_empty_evidence_result_without_fabricating_candidates(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            reverse("network-pharmacology"),
            {"herb": "不存在的中药", "disease": "不存在的疾病"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["targets"], [])
        self.assertEqual(response.data["summary"]["unmatchedHerbs"], ["不存在的中药"])
        self.assertEqual(response.data["summary"]["matchedDiseases"], [])

    def test_formula_query_expands_to_its_versioned_herb_relations(self):
        formula = self.entity(KnowledgeEntity.EntityType.FORMULA, "formula:fixture", "测试方剂")
        self.relation("formula_herb", formula, self.herb, "fh:1")
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            reverse("network-pharmacology"),
            {"herb": "测试方剂", "disease": "肺纤维化"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["summary"]["matchedFormulas"], ["测试方剂"])
        self.assertEqual(response.data["summary"]["matchedHerbs"], ["黄芩"])
        self.assertEqual(response.data["summary"]["strictIntersectionCount"], 1)
        formula_link = next(link for link in response.data["network"]["links"] if link["relation"] == "formula_herb")
        self.assertEqual(formula_link["sourceRecordId"], "fh:1")
        task = AnalysisTask.objects.get(pk=response.data["taskId"])
        self.assertIn("formula:fixture", task.input_parameters["formulas"])
        self.assertIn(self.release, task.source_releases.all())

    def test_accepted_case_formula_creates_a_linked_network_task_and_stale_cases_are_rejected(self):
        case = MedicalCase.objects.create(
            owner=self.owner,
            title="来源医案",
            deidentified_text="胸闷气短",
            structured_data={"diagnosis": "肺纤维化"},
        )
        formula = self.entity(KnowledgeEntity.EntityType.FORMULA, "formula:accepted", "已确认测试方剂")
        self.relation("formula_herb", formula, self.herb, "accepted:fh:1")
        case_task = AnalysisTask.objects.create(
            owner=self.owner,
            created_by=self.owner,
            task_type=AnalysisTask.TaskType.CASE_LINK,
            status=AnalysisTask.Status.SUCCEEDED,
            medical_case=case,
            input_parameters={"caseContentSha256": case_input_sha256(case)},
        )
        candidate = MedicalCaseCandidate.objects.create(
            task=case_task,
            medical_case=case,
            candidate_type=MedicalCaseCandidate.CandidateType.FORMULA,
            label=formula.label,
            entity=formula,
            match_status=MedicalCaseCandidate.MatchStatus.EXACT,
            confidence="0.9000",
            rank=1,
            review_status=MedicalCaseCandidate.ReviewStatus.ACCEPTED,
        )
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            reverse("network-pharmacology"),
            {
                "herb": formula.label,
                "disease": "肺纤维化",
                "source_case_id": case.pk,
                "source_candidate_id": candidate.pk,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        task = AnalysisTask.objects.get(pk=response.data["taskId"])
        self.assertEqual(task.medical_case, case)
        self.assertEqual(task.owner, self.owner)
        self.assertEqual(task.input_parameters["sourceCandidateId"], candidate.pk)
        self.assertEqual(task.input_parameters["sourceFormulaStableId"], formula.stable_id)

        case.deidentified_text += "后来补充的内容"
        case.save(update_fields=["deidentified_text", "updated_at"])
        stale = self.client.post(
            reverse("network-pharmacology"),
            {
                "herb": formula.label,
                "disease": "肺纤维化",
                "source_case_id": case.pk,
                "source_candidate_id": candidate.pk,
            },
            format="json",
        )
        self.assertEqual(stale.status_code, 400)
        self.assertEqual(AnalysisTask.objects.filter(task_type=AnalysisTask.TaskType.NETWORK).count(), 1)
