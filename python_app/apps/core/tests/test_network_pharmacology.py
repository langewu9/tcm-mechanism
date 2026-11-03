from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, MedicalCase, MedicalCaseCandidate, SourceRelease
from apps.core.services.case_analysis import case_input_sha256
from apps.core.services.network_pharmacology import RAW_EVIDENCE_VERSION, build_network_pharmacology


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

    def test_entity_neighborhood_returns_both_directions_with_source_versions(self):
        url = reverse("entity-neighborhood", args=[self.tp53.pk])
        self.assertEqual(self.client.get(url).status_code, 401)

        self.client.force_authenticate(self.owner)
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["entity"]["stable_id"], "protein:tp53")
        self.assertFalse(response.data["truncated"])
        self.assertEqual(
            {(item["subject_label"], item["relation_type"], item["object_label"], item["source_version"])
             for item in response.data["relations"]},
            {
                ("黄芩苷", "targets", "TP53", "fixture-v1"),
                ("肺纤维化", "disease_target", "TP53", "fixture-v1"),
                ("TP53", "participatesin", "细胞应激响应", "fixture-v1"),
            },
        )

    def test_entity_neighborhood_caps_large_relation_payloads(self):
        objects = [
            KnowledgeEntity(
                entity_type=KnowledgeEntity.EntityType.GENE,
                stable_id=f"gene:catalog-{index}",
                label=f"CATALOG{index}",
                source_release=self.release,
            )
            for index in range(201)
        ]
        KnowledgeEntity.objects.bulk_create(objects)
        EvidenceRelation.objects.bulk_create([
            EvidenceRelation(
                source_release=self.release,
                source_record_id=f"catalog-edge:{index}",
                subject=self.herb,
                object=entity,
                relation_type="catalog_annotation",
                evidence_type="fixture",
            )
            for index, entity in enumerate(objects)
        ])
        self.client.force_authenticate(self.owner)

        response = self.client.get(reverse("entity-neighborhood", args=[self.herb.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["relations"]), 200)
        self.assertTrue(response.data["truncated"])

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
        self.assertEqual(response.data["raw"], {
            "herbLinks": [], "diseaseTargets": [], "diseaseHerbLinks": [], "directDiseaseHerbLinks": [],
        })
        self.assertFalse(any(response.data["rawLimits"]["tablesTruncated"].values()))

    def test_raw_tables_keep_non_candidate_evidence_and_both_source_records(self):
        herb_only = self.entity("protein", "protein:herb-only", "HERB_ONLY")
        disease_only = self.entity("protein", "protein:disease-only", "DISEASE_ONLY")
        other_herb = self.entity("herb", "herb:other", "另一味中药")
        self.relation("targets", self.compound, herb_only, "herb-only:1")
        self.relation("disease_target", self.disease, disease_only, "disease-only:1")
        self.relation("disease_herb_target", self.disease, disease_only, "other-herb:1", {
            "herbStableId": other_herb.stable_id, "herbLabel": self.herb.label,
        })
        self.relation("disease_herb_target", self.disease, disease_only, "display-label-only:1", {
            "herbLabel": self.herb.label,
        })
        second_release = SourceRelease.objects.create(
            source=self.source, version="fixture-v2", checksum_sha256="a" * 64,
        )
        second_relation = EvidenceRelation.objects.create(
            source_release=second_release, subject=self.compound, object=self.tp53,
            source_record_id="cross-release:1", relation_type="targets", evidence_type="fixture-v2",
        )
        self.client.force_authenticate(self.owner)
        response = self.client.post(reverse("network-pharmacology"), {
            "herb": self.herb.label, "disease": self.disease.label,
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        raw = response.data["raw"]
        self.assertNotIn("HERB_ONLY", {item["target"] for item in response.data["targets"]})
        self.assertNotIn("DISEASE_ONLY", {item["target"] for item in response.data["targets"]})
        self.assertIn("HERB_ONLY", {item["target"] for item in raw["herbLinks"]})
        self.assertIn("DISEASE_ONLY", {item["target"] for item in raw["diseaseTargets"]})
        cross = next(item for item in raw["herbLinks"] if item["relationId"] == second_relation.pk)
        self.assertEqual(cross["sourceVersion"], "fixture-v2")
        self.assertEqual(cross["sourceChecksumSha256"], "a" * 64)
        self.assertEqual(cross["herbSourceVersion"], "fixture-v1")
        self.assertEqual(cross["herbSourceChecksumSha256"], "f" * 64)
        self.assertEqual(cross["herbSourceRecordId"], "hct:1")
        self.assertEqual(cross["herbStableId"], self.herb.stable_id)
        self.assertEqual(cross["componentStableId"], self.compound.stable_id)
        self.assertEqual(cross["targetStableId"], self.tp53.stable_id)
        self.assertEqual([item["sourceRecordId"] for item in raw["directDiseaseHerbLinks"]], ["dht:1"])
        other = next(item for item in raw["diseaseHerbLinks"] if item["sourceRecordId"] == "other-herb:1")
        self.assertEqual(other["herb"], other_herb.label)
        unresolved = next(item for item in raw["diseaseHerbLinks"] if item["sourceRecordId"] == "display-label-only:1")
        self.assertEqual(unresolved["herb"], "")
        self.assertEqual(unresolved["herbIdentityStatus"], "unresolved")
        task = AnalysisTask.objects.get(pk=response.data["taskId"])
        self.assertEqual(task.input_parameters["rawEvidenceVersion"], RAW_EVIDENCE_VERSION)
        self.assertEqual(task.result["raw"], raw)
        self.herb.label = "后来改名"
        self.herb.save(update_fields=["label"])
        saved = self.client.get(reverse("analysis-task-detail", args=[task.pk]))
        self.assertEqual(saved.data["result"]["raw"], raw)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(reverse("analysis-task-detail", args=[task.pk])).status_code, 404)

    def test_raw_join_stops_at_export_cap_with_separate_source_provenance(self):
        for index in range(25):
            self.relation("contains", self.herb, self.compound, f"join-herb:{index}")
            self.relation("targets", self.compound, self.tp53, f"join-target:{index}")
        self.client.force_authenticate(self.owner)
        response = self.client.post(reverse("network-pharmacology"), {
            "herb": self.herb.label, "disease": self.disease.label, "limit": 500,
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["raw"]["herbLinks"]), 500)
        limits = response.data["rawLimits"]
        self.assertEqual(limits["rowLimit"], 500)
        self.assertTrue(limits["tablesTruncated"]["herbLinks"])
        self.assertFalse(any(limits["inputRelationsTruncated"].values()))
        self.assertFalse(limits["tablesTruncated"]["directDiseaseHerbLinks"])
        self.assertEqual(len({(row["relationId"], row["herbRelationId"])
                              for row in response.data["raw"]["herbLinks"]}), 500)

    def test_input_relation_sentinel_reports_partial_scope_without_changing_statistics(self):
        result = build_network_pharmacology(
            user=self.owner, herb_query=self.herb.label, disease_query=self.disease.label,
            row_limit=2, persist=False,
        )
        self.assertTrue(result["rawLimits"]["inputRelationsTruncated"]["diseaseTargets"])
        self.assertEqual(result["summary"]["diseaseTargetCount"], 2)
        self.assertEqual(result["summary"]["directAssociationTargetCount"], 1)
        self.assertEqual({row["sourceRecordId"] for row in result["raw"]["diseaseTargets"]}, {"dt:1", "dt:2"})
        self.assertEqual(result["raw"]["directDiseaseHerbLinks"], [])
        self.assertFalse(AnalysisTask.objects.exists())

    def test_network_search_hides_entities_from_disabled_sources(self):
        disabled_source = DataSource.objects.create(slug="disabled", name="停用来源", enabled=False)
        disabled_release = SourceRelease.objects.create(
            source=disabled_source, version="disabled-v1", checksum_sha256="d" * 64,
        )
        hidden_herb = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.HERB,
            stable_id="herb:hidden", label="停用来源药材", source_release=disabled_release,
        )
        hidden_compound = KnowledgeEntity.objects.create(
            entity_type=KnowledgeEntity.EntityType.COMPOUND,
            stable_id="compound:hidden", label="停用来源成分", source_release=disabled_release,
        )
        self.relation("contains", self.herb, hidden_compound, "enabled-edge-hidden-endpoint")
        self.relation("contains", hidden_herb, self.compound, "enabled-edge-hidden-herb")
        self.relation("targets", hidden_compound, self.akt1, "enabled-edge-hidden-target")
        self.client.force_authenticate(self.owner)

        hidden_search = self.client.post(
            reverse("network-pharmacology"),
            {"herb": "停用来源药材", "disease": "肺纤维化"},
            format="json",
        )
        self.assertEqual(hidden_search.status_code, 200)
        self.assertEqual(hidden_search.data["summary"]["matchedHerbs"], [])
        self.assertEqual(hidden_search.data["summary"]["unmatchedHerbs"], ["停用来源药材"])
        batch_hidden = self.client.post(
            reverse("batch-herb-evidence"),
            {"queryType": "herb", "queries": ["停用来源药材"]},
            format="json",
        )
        self.assertEqual(batch_hidden.status_code, 200)
        self.assertEqual(batch_hidden.data["results"][0]["matches"], [])

        enabled_search = self.client.post(
            reverse("network-pharmacology"),
            {"herb": "黄芩", "disease": "肺纤维化"},
            format="json",
        )
        self.assertEqual(enabled_search.status_code, 200)
        node_labels = {node["label"] for node in enabled_search.data["network"]["nodes"]}
        self.assertNotIn("停用来源药材", node_labels)
        self.assertNotIn("停用来源成分", node_labels)
        batch_enabled = self.client.post(
            reverse("batch-herb-evidence"),
            {"queryType": "herb", "queries": ["黄芩"]},
            format="json",
        )
        self.assertEqual(batch_enabled.status_code, 200)
        self.assertNotIn("停用来源成分", {item["label"] for item in batch_enabled.data["results"][0]["compounds"]})
        source_record_ids = {
            source["sourceRecordId"]
            for target in enabled_search.data["targets"]
            for source in target["sources"]
        }
        self.assertNotIn("enabled-edge-hidden-target", source_record_ids)
        raw = enabled_search.data["raw"]
        self.assertNotIn("停用来源成分", {item["component"] for item in raw["herbLinks"]})
        self.assertNotIn("enabled-edge-hidden-target", {item["sourceRecordId"] for item in raw["herbLinks"]})

    def test_batch_herb_and_compound_evidence_returns_versioned_edges(self):
        url = reverse("batch-herb-evidence")
        self.assertEqual(self.client.post(url, {"queryType": "herb", "queries": ["黄芩"]}, format="json").status_code, 401)
        self.client.force_authenticate(self.owner)

        herbs = self.client.post(
            url,
            {"queryType": "herb", "queries": ["黄芩", "不存在的中药"]},
            format="json",
        )
        self.assertEqual(herbs.status_code, 200, herbs.data)
        herb_result, missing_result = herbs.data["results"]
        self.assertEqual(herb_result["compounds"][0]["label"], "黄芩苷")
        self.assertEqual(herb_result["targets"][0]["label"], "TP53")
        self.assertEqual({item["sourceVersion"] for item in herb_result["relations"]}, {"fixture-v1"})
        self.assertEqual([item["sourceRecordId"] for item in herb_result["relations"]], ["hct:1", "hct:2"])
        self.assertEqual(missing_result["matches"], [])
        self.assertEqual(missing_result["relations"], [])

        compounds = self.client.post(
            url,
            {"queryType": "compound", "queries": ["黄芩苷"]},
            format="json",
        )
        self.assertEqual(compounds.status_code, 200, compounds.data)
        self.assertEqual(compounds.data["results"][0]["herbs"][0]["label"], "黄芩")
        self.assertEqual(compounds.data["results"][0]["targets"][0]["label"], "TP53")

        excessive = self.client.post(
            url,
            {"queryType": "herb", "queries": [f"药材{i}" for i in range(13)]},
            format="json",
        )
        self.assertEqual(excessive.status_code, 400)

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
