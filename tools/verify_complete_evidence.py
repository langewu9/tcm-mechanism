"""Verify frozen complete analyses against the earlier eight real cap samples.

Creates/destroys a disposable PostgreSQL database. No provider/model calls or
real research writes. Network comparison covers the herb side (no disease match).
Uses production import, query, task, pagination and streaming export code.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time

from postgres_acceptance import APP, environment


def run(sample):
    environment()
    os.environ["CACHE_URL"] = ""
    sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import connection, transaction
    from rest_framework.test import APIClient
    from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease
    from apps.core.services.complete_evidence import VERSION, canonical, digest
    from apps.core.services.herb_evidence import batch_herb_component_evidence
    from apps.core.tasks import run_complete_evidence_task
    from apps.sources.legacy_identity import check_identity_consistency
    from apps.sources.sqlite_sync import EVIDENCE_TYPE, _row_entities_and_relations

    assert connection.vendor == "postgresql" and connection.settings_dict["NAME"] == "tcm_acceptance"
    def live_state():
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
            return {"tasks": digest(list(AnalysisTask.objects.order_by("pk").values("id", "owner_id", "created_by_id", "input_parameters", "result", "status"))),
                    "evidence": digest(list(EvidenceRelation.objects.order_by("pk").values("id", "subject_id", "object_id", "source_release_id", "metadata", "is_active")))}
    before = live_state()
    original = connection.settings_dict["NAME"]
    connection.settings_dict.setdefault("TEST", {})["NAME"] = "test_complete_evidence_" + secrets.token_hex(6)
    created = False
    report = {"scope": __doc__, "workbooks": sample["workbooks"], "cases": [], "externalCalls": False}
    try:
        connection.creation.create_test_db(verbosity=0, autoclobber=False, serialize=False)
        created = True
        sources, releases, entities, specs, proofs = {}, {}, {}, [], {}
        for workbook in sample["workbooks"]:
            provider = workbook["provider"]
            sources[provider] = DataSource.objects.create(slug=f"complete-verify-{provider}", name=f"TEMP {provider}",
                configuration={"connector": "sqlite-herb-compound-target", "targetCellMode": "single"})
            releases[provider] = SourceRelease.objects.create(source=sources[provider], version="complete-evidence-verification",
                checksum_sha256=workbook["sha256"], metadata={"connector": "sqlite-herb-compound-target"})
        for row in sample["rows"]:
            incoming = ("herb", row["row"], *row["values"])
            if row["record"] is not None:
                incoming += (row["record"],)
            payloads, edges = _row_entities_and_relations(sources[row["provider"]], incoming)
            for payload in payloads:
                check_identity_consistency(payload, proofs)
                entities[payload["stable_id"]] = KnowledgeEntity(**payload, source_release=releases[row["provider"]])
            specs.extend((row["provider"], edge, row["values"][0]) for edge in edges)
        KnowledgeEntity.objects.bulk_create(entities.values(), batch_size=500)
        ids = dict(KnowledgeEntity.objects.values_list("stable_id", "pk"))
        rows, expected = [], {}
        for provider, spec, herb in specs:
            kind, subject, object_, record, row_id, metadata = spec
            edge = EvidenceRelation(source_release=releases[provider], subject_id=ids[subject], object_id=ids[object_],
                relation_type=kind, source_record_id=record, evidence_type=EVIDENCE_TYPE,
                metadata={"sourceRowId": row_id, "source": sources[provider].slug, **metadata})
            rows.append(edge)
        EvidenceRelation.objects.bulk_create(rows, batch_size=500)
        for (provider, spec, herb), edge in zip(specs, rows):
            oracle = expected.setdefault((provider, herb), {"edges": set(), "targets": set()})
            oracle["edges"].add(edge.pk)
            if spec[0] == "targets":
                oracle["targets"].add(ids[spec[2]])
        owner = get_user_model().objects.create_user(username="complete-real-sample-owner")
        other = get_user_model().objects.create_user(username="complete-real-sample-other")
        client = APIClient()
        client.force_authenticate(owner)
        cases = [*sample["cases"], {"provider": "both", "herb": "、".join(dict.fromkeys(case["herb"] for case in sample["cases"]))}]
        for case in cases:
            provider, names = case["provider"], case["herb"].split("、")
            DataSource.objects.update(enabled=False)
            DataSource.objects.filter(pk__in=[source.pk for key, source in sources.items() if provider == "both" or key == provider]).update(enabled=True)
            keys = [key for key in expected if key[1] in names and (provider == "both" or key[0] == provider)]
            oracle_edges = set().union(*(expected[key]["edges"] for key in keys))
            oracle_targets = set().union(*(expected[key]["targets"] for key in keys))
            preview = batch_herb_component_evidence(query_type="herb", queries=names)
            for kind in ("catalog_evidence", "network_pharmacology"):
                started = time.perf_counter()
                params = {"analysisKind": kind, "algorithmVersion": VERSION, "complete": True}
                if kind == "catalog_evidence":
                    params.update(queryType="herb", queries=names, expectedResultSha256=preview["resultSha256"])
                else:
                    params.update(herb=case["herb"], disease="NO_MATCH_COMPLETE_EVIDENCE_VERIFICATION")
                task = AnalysisTask.objects.create(owner=owner, created_by=owner, task_type="network", input_parameters=params)
                assert run_complete_evidence_task(task.pk)["status"] == "succeeded"
                task.refresh_from_db()
                manifest = task.result["snapshot"]
                actual = set(task.snapshot_rows.filter(table="evidenceRecords").values_list("payload__id", flat=True))
                assert actual == oracle_edges, (case, kind, "source row set differs")
                target_ids = set(task.snapshot_rows.filter(table="entities", payload__type__in=["target", "gene", "protein"]).values_list("payload__id", flat=True))
                assert target_ids == oracle_targets, (case, kind, "target identities differ")
                assert manifest["complete"] and not task.result.get("limits", {}).get("queryTruncated", False)
                base = f"/api/v1/research/analysis-tasks/{task.pk}"
                hashes = {name: hashlib.sha256() for name in manifest["tables"]}
                counts = {name: 0 for name in manifest["tables"]}
                exported = client.get(base + "/snapshot-export/")
                assert exported.status_code == 200
                for chunk in exported.streaming_content:
                    # Each application chunk is one JSONL record, not a TCP packet.
                    record = json.loads(chunk)
                    if record["type"] == "manifest":
                        sha = record["snapshot"].pop("sha256")
                        assert sha == digest({"parameters": record["parameters"], "result": record["result"], "manifest": record["snapshot"]})
                        continue
                    table = record["table"]
                    counts[table] += 1
                    assert record["ordinal"] == counts[table]
                    hashes[table].update((canonical(record["payload"]) + "\n").encode())
                for name, info in manifest["tables"].items():
                    assert counts[name] == info["count"] and hashes[name].hexdigest() == info["sha256"]
                for page in {1, (len(oracle_edges) + 19) // 20}:
                    response = client.get(base + f"/snapshot-rows/?page={page}&page_size=20")
                    assert response.status_code == 200 and response.data["count"] == len(oracle_edges)
                    assert response.data["snapshotSha256"] == manifest["sha256"]
                table = "evidenceRecords" if kind == "catalog_evidence" else "herbLinks"
                exported = client.get(base + f"/snapshot-export/?table={table}&file_format=csv")
                csv_rows = csv.DictReader(chunk.decode("utf-8-sig") for chunk in exported.streaming_content)
                csv_count = sum(1 for _ in csv_rows)
                assert csv_count == manifest["tables"][table]["count"]
                if kind == "network_pharmacology":
                    assert task.result["summary"]["herbTargetCount"] == len(oracle_targets)
                    assert manifest["tables"]["herbLinks"]["count"] == len(oracle_edges) // 2
                    assert not any(task.result["rawLimits"]["inputRelationsTruncated"].values())
                client.force_authenticate(other)
                assert client.get(base + "/snapshot-rows/").status_code == 404
                assert client.get(base + "/snapshot-export/").status_code == 404
                client.force_authenticate(owner)
                item = {"provider": provider, "herb": case["herb"], "kind": kind, "sourceHerbKeys": len(keys),
                        "expectedEdges": len(oracle_edges), "actualEdges": len(actual), "targets": len(target_ids),
                        "exportedCsvRows": csv_count, "tables": manifest["tables"], "snapshotSha256": manifest["sha256"],
                        "seconds": round(time.perf_counter() - started, 3), "sourceIdentitySetMatches": True,
                        "allTableHashesMatch": True, "paginationBoundaryMatches": True, "otherAccountDenied": True}
                report["cases"].append(item)
                print(json.dumps({key: item[key] for key in ("provider", "herb", "kind", "actualEdges", "targets", "seconds")}, ensure_ascii=False), flush=True)
    finally:
        if created:
            connection.creation.destroy_test_db(old_database_name=original, verbosity=0)
        else:
            connection.settings_dict["NAME"] = original
    assert live_state() == before, "Live research/evidence changed; inspect before proceeding."
    report.update(temporaryDatabaseDestroyed=True, liveResearchAndEvidenceUnchanged=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite an earlier verification report.")
    sample = json.loads(args.sample.read_text())
    report = run(sample)
    report["sampleSha256"] = hashlib.sha256(args.sample.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"passed": True, "cases": len(report["cases"]), "report": str(args.output)}), flush=True)


if __name__ == "__main__":
    main()
