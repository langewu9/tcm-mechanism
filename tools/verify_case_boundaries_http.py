"""Read-only localhost case/candidate guards, without creating model results.

Positive confirmed-chain cases belong to isolated backend tests. This checks
the existing work database's missing-candidate state and owner boundary only.
"""
import json
from pathlib import Path
import sys

from postgres_acceptance import APP, VAR, environment
from smoke_local_workspace import LocalClient
from audit_text_workbench import fingerprint

JOB = APP / "var/case-boundary-2026-10-22"


def save(name, value):
    path = JOB / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)); path.chmod(0o600)


def main():
    JOB.mkdir(parents=True, exist_ok=True); JOB.chmod(0o700)
    if (JOB / "http-verified.json").exists():
        raise ValueError("Completed verification exists; do not replace evidence.")
    environment(); sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.db import connection, transaction
    from django.db.models import Max
    from apps.core.models import AnalysisTask, KnowledgeEntity, MedicalCase, MedicalCaseCandidate

    accounts = json.loads((VAR / "accounts.json").read_text())
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
        counts = {"cases": MedicalCase.objects.count(), "candidates": MedicalCaseCandidate.objects.count(),
                  "tasks": AnalysisTask.objects.count(),
                  "syndromes": KnowledgeEntity.objects.filter(entity_type="syndrome", is_active=True).count(),
                  "formulas": KnowledgeEntity.objects.filter(entity_type="formula", is_active=True).count()}
        if counts["candidates"]:
            raise ValueError("This negative-case check requires the verified missing-candidate state.")
        case_id = MedicalCase.objects.filter(owner_id=accounts["a"]["id"], archived_at__isnull=True).values_list("pk", flat=True).first()
        if not case_id: raise ValueError("No existing researcher-a acceptance case; do not create one automatically.")
        missing_id = (MedicalCaseCandidate.objects.aggregate(value=Max("pk"))["value"] or 0) + 100000
    before = fingerprint(); save("before.json", before)
    clients = [LocalClient(accounts[key], base_url="http://127.0.0.1:5174", csrf_cookie_name="tcm_pg_csrf")
               for key in ("a", "b", "admin")]
    owner, other, admin = clients
    try:
        base = f"/api/v1/research/cases/{case_id}"
        _, state = owner.request(base + "/analysis/")
        assert not state["candidates"] and not state["modelConfiguration"]["configured"]
        other.request(base + "/", expected=404)
        other.request(base + "/analysis/", expected=404)
        _, admin_case = admin.request(base + "/"); assert admin_case["owner_id"] == accounts["a"]["id"]
        for complete in (False, True):
            owner.request("/api/v1/analysis/network-pharmacology/", method="POST", expected=404, data={
                "herb": "SYNTHETIC_UNCONFIRMED_FORMULA", "disease": "SYNTHETIC_NO_DISEASE",
                "source_case_id": case_id, "source_candidate_id": missing_id, "complete": complete})
        owner.request(base + f"/candidates/{missing_id}/review/", method="POST", expected=404, data={"decision": "accept"})
        assert fingerprint(before) == before, "Existing research or catalogue changed."
        assert AnalysisTask.objects.count() == counts["tasks"] and not MedicalCaseCandidate.objects.exists()
        proof = {"passed": True, "existingCounts": counts, "caseId": case_id,
                 "otherOwnerDenied": True, "adminPreservesOwner": True,
                 "missingCandidateCannotConfirm": True, "missingCandidateCannotQueueOrSaveNetwork": True,
                 "previousRecordHashesUnchanged": True, "newTasks": 0, "newCandidates": 0,
                 "modelConfigured": False, "modelCalls": False, "externalCalls": False,
                 "positiveRealCaseValidated": False}
        save("http-verified.json", proof)
        print(json.dumps(proof, ensure_ascii=False))
    finally:
        for client in clients:
            client.request("/api/v1/auth/session/", method="DELETE", expected=204)


if __name__ == "__main__":
    main()
