"""Local confirmed-case boundaries with synthetic candidates; no model is run."""
from unittest.mock import patch
from threading import Event, Thread
import time

from django.contrib.auth import get_user_model
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, MedicalCase, MedicalCaseCandidate, SourceRelease
from apps.core.services.case_analysis import build_confirmed_evidence_chain, case_input_sha256
from apps.core.services.complete_evidence import digest
from apps.core.tasks import run_complete_evidence_task


@override_settings(SECURE_SSL_REDIRECT=False)
class ConfirmedCaseEvidenceBoundaryTests(TransactionTestCase):
    def setUp(self):
        guard = patch("apps.core.services.case_analysis._local_model_response", side_effect=AssertionError("No model calls"))
        guard.start(); self.addCleanup(guard.stop)
        self.owner = get_user_model().objects.create_user(username="case-boundary-owner")
        self.other = get_user_model().objects.create_user(username="case-boundary-other")
        self.client = APIClient(); self.client.force_authenticate(self.owner)
        self.case = MedicalCase.objects.create(owner=self.owner, title="SYNTHETIC boundary fixture",
            deidentified_text="合成医案文字，仅验证权限和来源，不代表临床资料。")
        self.source = DataSource.objects.create(slug="case-curated-fixture", name="合成方剂关联")
        self.release = SourceRelease.objects.create(source=self.source, version="v1", checksum_sha256="a" * 64)
        self.triple_source = DataSource.objects.create(slug="case-row-fixture", name="合成原行资料")
        self.triples = SourceRelease.objects.create(source=self.triple_source, version="rows-v1", checksum_sha256="b" * 64,
            metadata={"connector": "sqlite-herb-compound-target"})
        self.formula = self.entity("formula", "合成方剂")
        self.herb = self.entity("herb", "合成中药", self.triples)
        self.compound = self.entity("compound", "合成共享成分", self.triples)
        self.target = self.entity("protein", "SELECTED_TARGET", self.triples)
        self.pathway = self.entity("pathway", "合成通路")
        self.edge("formula_herb", self.formula, self.herb, "formula-herb")
        self.edge("contains", self.herb, self.compound, "selected-herb", release=self.triples, row=1)
        self.edge("targets", self.compound, self.target, "selected-target", release=self.triples, row=1)
        self.edge("protein_pathway", self.target, self.pathway, "selected-pathway")
        self.task = AnalysisTask.objects.create(owner=self.owner, created_by=self.owner, task_type="case_link",
            medical_case=self.case, status="succeeded", input_parameters={"caseContentSha256": case_input_sha256(self.case)},
            result={"analysisKind": "case_analysis", "fixtureOnly": True, "observations": []})
        self.candidate = MedicalCaseCandidate.objects.create(task=self.task, medical_case=self.case,
            candidate_type="formula", entity=self.formula, label=self.formula.label, match_status="exact",
            confidence="0.8", rank=1, evidence=[], review_status="pending")

    def entity(self, kind, label, release=None):
        return KnowledgeEntity.objects.create(entity_type=kind, stable_id=f"synthetic:{kind}:{label}",
            label=label, source_release=release or self.release)

    def edge(self, kind, subject, object_, record, *, release=None, row=None):
        return EvidenceRelation.objects.create(subject=subject, object=object_, relation_type=kind,
            source_record_id=record, source_release=release or self.release,
            metadata={"sourceRowId": row} if row is not None else {})

    def chain(self):
        self.candidate.review_status = "accepted"; self.candidate.save(update_fields=["review_status"])
        candidates = MedicalCaseCandidate.objects.filter(task=self.task).select_related("entity__source_release__source")
        return build_confirmed_evidence_chain(candidates)[0]

    def review(self, decision="accept"):
        return self.client.post(reverse("case-review-candidate", args=[self.case.pk, self.candidate.pk]),
            {"decision": decision}, format="json")

    def linked(self, *, complete=False):
        return self.client.post(reverse("network-pharmacology"), {"herb": self.formula.label,
            "disease": "合成疾病", "source_case_id": self.case.pk, "source_candidate_id": self.candidate.pk,
            "complete": complete}, format="json")

    def test_shared_compound_does_not_bring_another_herbs_target_or_pathway(self):
        foreign = self.entity("protein", "OTHER_HERB_TARGET", self.triples)
        self.edge("targets", self.compound, foreign, "other-herb-row", release=self.triples, row=2)
        self.edge("protein_pathway", foreign, self.pathway, "other-herb-pathway")
        chain = self.chain()
        self.assertNotIn(foreign.pk, {node["id"] for node in chain["nodes"]})
        self.assertEqual({link["sourceRecordId"] for link in chain["links"]},
            {"formula-herb", "selected-herb", "selected-target", "selected-pathway"})

    def test_invalid_row_types_and_other_release_cannot_establish_herb_support(self):
        foreign = self.entity("protein", "INVALID_ROW_TARGET", self.triples)
        for i, row in enumerate([None, "1", True, 1.0]):
            self.edge("targets", self.compound, foreign, f"invalid:{i}", release=self.triples, row=row)
        second = SourceRelease.objects.create(source=self.triple_source, version="rows-v2", metadata=self.triples.metadata)
        self.edge("targets", self.compound, foreign, "other-release", release=second, row=1)
        chain = self.chain()
        self.assertNotIn(foreign.pk, {node["id"] for node in chain["nodes"]})
        self.assertNotIn(second.pk, {source["id"] for source in chain["sources"]})

    def test_disabled_relation_or_endpoint_source_does_not_supply_a_chain(self):
        hidden = DataSource.objects.create(slug="case-disabled", name="停用的合成来源", enabled=False)
        release = SourceRelease.objects.create(source=hidden, version="hidden-v1")
        hidden_target = self.entity("protein", "DISABLED_ENDPOINT", release)
        visible_target = self.entity("protein", "DISABLED_RELATION")
        self.edge("compound_gene", self.compound, hidden_target, "hidden-endpoint")
        self.edge("compound_gene", self.compound, visible_target, "hidden-relation", release=release)
        chain = self.chain()
        ids = {node["id"] for node in chain["nodes"]}
        self.assertFalse(ids & {hidden_target.pk, visible_target.pk})
        self.assertNotIn(release.pk, {source["id"] for source in chain["sources"]})

    def test_endpoint_types_alone_do_not_turn_negative_relations_into_composition(self):
        foreign = self.entity("compound", "NEGATIVE_COMPOSITION")
        self.edge("does_not_contain", self.herb, foreign, "negative-composition")
        chain = self.chain()
        self.assertNotIn(foreign.pk, {node["id"] for node in chain["nodes"]})

    def test_scope_filter_precedes_cap_and_exact_terminal_cap_is_not_truncated(self):
        foreign = self.entity("protein", "CAP_FOREIGN", self.triples)
        self.edge("targets", self.compound, foreign, "wrong-row-before-cap", release=self.triples, row=2)
        with patch("apps.core.services.case_analysis.MAX_EVIDENCE_CHAIN_RELATIONS", 4):
            chain = self.chain()
        self.assertEqual(len(chain["links"]), 4)
        self.assertIn(self.pathway.pk, {node["id"] for node in chain["nodes"]})
        self.assertFalse(chain["truncated"])

    def test_generic_annotations_remain_valid_and_all_edges_have_endpoints(self):
        generic = self.entity("gene", "GENERIC_ANNOTATION")
        self.edge("compound_gene", self.compound, generic, "generic-annotation")
        chain = self.chain(); ids = {node["id"] for node in chain["nodes"]}
        self.assertIn(generic.pk, ids)
        self.assertTrue(all(link["source"] in ids and link["target"] in ids for link in chain["links"]))

    def test_accept_rejects_inactive_or_disabled_candidate_without_rewriting_task(self):
        before = digest(self.task.result)
        self.formula.is_active = False; self.formula.save(update_fields=["is_active"])
        self.assertEqual(self.review().status_code, 400)
        self.formula.is_active = True; self.formula.save(update_fields=["is_active"])
        self.source.enabled = False; self.source.save(update_fields=["enabled"])
        self.assertEqual(self.review().status_code, 400)
        self.candidate.refresh_from_db(); self.task.refresh_from_db()
        self.assertEqual(self.candidate.review_status, "pending")
        self.assertEqual(digest(self.task.result), before)

    def test_wrong_entity_type_is_not_confirmed_as_a_formula(self):
        self.candidate.entity = self.target; self.candidate.save(update_fields=["entity"])
        self.assertEqual(self.review().status_code, 400)

    def test_inactive_accepted_roots_are_excluded_with_a_reason_on_explicit_rebuild(self):
        self.formula.is_active = False; self.formula.save(update_fields=["is_active"])
        chain = self.chain()
        self.assertEqual(chain["nodes"], [])
        self.assertEqual(chain["links"], [])
        self.assertTrue(chain["warnings"])

    def test_confirmation_freezes_original_row_identity_and_plain_reads_do_not_rebuild(self):
        response = self.review(); self.assertEqual(response.status_code, 200, response.data)
        self.task.refresh_from_db(); before = digest(self.task.result)
        chain = self.task.result["evidenceChain"]
        row = next(link for link in chain["links"] if link["sourceRecordId"] == "selected-target")
        self.assertEqual(row["sourceRowId"], 1)
        self.assertEqual(row["sourceReleaseId"], self.triples.pk)
        self.assertEqual(row["sourceChecksumSha256"], "b" * 64)
        self.assertEqual(row["subjectStableId"], self.compound.stable_id)
        self.triple_source.enabled = False; self.triple_source.save(update_fields=["enabled"])
        self.assertEqual(self.client.get(reverse("case-analysis", args=[self.case.pk])).status_code, 200)
        self.task.refresh_from_db(); self.assertEqual(digest(self.task.result), before)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.review("reject").status_code, 404)

    def test_archived_case_and_unavailable_formula_do_not_create_linked_tasks(self):
        self.chain(); self.case.archived_at = timezone.now(); self.case.save(update_fields=["archived_at"])
        with patch("apps.core.tasks.run_complete_evidence_task.apply_async") as dispatch:
            self.assertEqual(self.linked().status_code, 404)
            self.assertEqual(self.linked(complete=True).status_code, 404)
            dispatch.assert_not_called()
        self.case.archived_at = None; self.case.save(update_fields=["archived_at"])
        self.formula.is_active = False; self.formula.save(update_fields=["is_active"])
        with patch("apps.core.tasks.run_complete_evidence_task.apply_async") as dispatch:
            self.assertEqual(self.linked(complete=True).status_code, 400)
            dispatch.assert_not_called()
        self.assertFalse(AnalysisTask.objects.filter(task_type="network").exists())

    def test_archiving_after_queue_fails_closed_and_keeps_previous_complete_result(self):
        self.chain()
        with patch("apps.core.tasks.run_complete_evidence_task.apply_async"):
            response = self.linked(complete=True)
        self.assertEqual(response.status_code, 202, response.data)
        first = AnalysisTask.objects.get(pk=response.data["id"])
        self.assertEqual(run_complete_evidence_task(first.pk)["status"], "succeeded")
        first.refresh_from_db(); before = digest(first.result)
        with patch("apps.core.tasks.run_complete_evidence_task.apply_async"):
            response = self.linked(complete=True)
        queued = AnalysisTask.objects.get(pk=response.data["id"])
        self.case.archived_at = timezone.now(); self.case.save(update_fields=["archived_at"])
        self.assertEqual(run_complete_evidence_task(queued.pk)["status"], "failed")
        queued.refresh_from_db(); self.assertFalse(queued.snapshot_rows.exists())
        first.refresh_from_db(); self.assertEqual(digest(first.result), before)

    def test_syndrome_and_formula_roots_collect_all_herb_rows_before_shared_targets(self):
        syndrome = self.entity("syndrome", "合成证候")
        second_formula = self.entity("formula", "另一合成方剂")
        second_herb = self.entity("herb", "另一合成中药", self.triples)
        second_target = self.entity("protein", "SECOND_SELECTED_TARGET", self.triples)
        self.edge("syndrome_formula", syndrome, second_formula, "second-formula")
        self.edge("formula_herb", second_formula, second_herb, "second-herb")
        self.edge("contains", second_herb, self.compound, "second-herb-row", release=self.triples, row=2)
        self.edge("targets", self.compound, second_target, "second-target-row", release=self.triples, row=2)
        MedicalCaseCandidate.objects.create(task=self.task, medical_case=self.case, candidate_type="syndrome",
            entity=syndrome, label=syndrome.label, match_status="exact", confidence="0.7", rank=1,
            evidence=[], review_status="accepted")
        chain = self.chain(); ids = {node["id"] for node in chain["nodes"]}
        self.assertTrue({self.target.pk, second_target.pk} <= ids)
        self.assertFalse(chain["truncated"])

    def test_real_supported_overflow_is_reported_as_truncated(self):
        second = self.entity("protein", "SECOND_VALID_TARGET", self.triples)
        self.edge("targets", self.compound, second, "another-valid-target", release=self.triples, row=1)
        with patch("apps.core.services.case_analysis.MAX_EVIDENCE_CHAIN_RELATIONS", 3):
            chain = self.chain()
        self.assertEqual(len(chain["links"]), 3)
        self.assertTrue(chain["truncated"])

    def test_rejection_remains_available_after_candidate_source_is_disabled(self):
        self.assertEqual(self.review().status_code, 200)
        self.source.enabled = False; self.source.save(update_fields=["enabled"])
        self.assertEqual(self.review("reject").status_code, 200)
        self.task.refresh_from_db(); self.candidate.refresh_from_db()
        self.assertTrue(self.task.result["fixtureOnly"])
        self.assertEqual(self.candidate.review_status, "rejected")
        self.assertEqual(self.task.result["evidenceChain"]["links"], [])

    def test_postgres_worker_holds_case_lock_against_concurrent_archival(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL row lock required")
        from apps.core.services.complete_evidence import _source_candidate
        self.chain()
        probe = AnalysisTask(owner=self.owner, input_parameters={"sourceCaseId": self.case.pk,
            "sourceCandidateId": self.candidate.pk, "sourceFormulaStableId": self.formula.stable_id,
            "caseContentSha256": case_input_sha256(self.case)})
        result = {}
        def competing_archive_lock():
            close_old_connections()
            try:
                with transaction.atomic():
                    MedicalCase.objects.select_for_update(nowait=True).get(pk=self.case.pk)
                result["locked"] = False
            except DatabaseError as exc:
                result["locked"] = getattr(exc.__cause__, "sqlstate", "") == "55P03"
            finally:
                connection.close()
        with transaction.atomic():
            self.assertEqual(_source_candidate(probe).pk, self.candidate.pk)
            thread = Thread(target=competing_archive_lock); thread.start(); thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertTrue(result.get("locked"), result)

    def test_postgres_worker_waits_for_case_before_locking_candidate(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL lock ordering required")
        from apps.core.services.complete_evidence import _source_candidate
        self.chain()
        probe = AnalysisTask(owner=self.owner, input_parameters={"sourceCaseId": self.case.pk,
            "sourceCandidateId": self.candidate.pk, "sourceFormulaStableId": self.formula.stable_id,
            "caseContentSha256": case_input_sha256(self.case)})
        ready, result = Event(), {}
        def worker():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                        cursor.execute("SELECT pg_backend_pid()")
                        result["pid"] = cursor.fetchone()[0]
                    ready.set(); _source_candidate(probe)
                result["completed"] = True
            except Exception as exc:
                result["errorType"] = type(exc).__name__
            finally:
                connection.close()
        thread = Thread(target=worker)
        try:
            with transaction.atomic():
                MedicalCase.objects.select_for_update().get(pk=self.case.pk)
                thread.start(); self.assertTrue(ready.wait(timeout=3))
                waiting = False; deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_stat_clear_snapshot()")
                        cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [result["pid"]])
                        waiting = cursor.fetchone() == ("Lock",)
                    if waiting: break
                    time.sleep(.01)
                self.assertTrue(waiting, result)
                # The worker is waiting for our case lock. It must leave the
                # candidate free so the case-owning reviewer can finish.
                with transaction.atomic():
                    MedicalCaseCandidate.objects.select_for_update(nowait=True).get(pk=self.candidate.pk)
        finally:
            if thread.ident is not None: thread.join(timeout=6)
        self.assertFalse(thread.is_alive())
        self.assertTrue(result.get("completed"), result)
