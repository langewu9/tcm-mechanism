"""Serial production-query cap comparison on a disposable PostgreSQL database.

Uses eight complete real herb samples and bounded real background rows. No
concurrent load, research tasks, model/provider calls, or live configuration
changes. Network measurements cover the herb side, with an unmatched disease.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import secrets
import statistics
import sys
import time
from unittest.mock import patch

from postgres_acceptance import APP, environment


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run(sample, progress):
    environment()
    os.environ["CACHE_URL"] = ""
    sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.db import connection, transaction
    from apps.core.models import AnalysisTask, DataSource, EvidenceRelation, KnowledgeEntity, SourceRelease
    from apps.core.services import herb_evidence, network_pharmacology
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
    original_name = connection.settings_dict["NAME"]
    test_name = "test_herb_caps_" + secrets.token_hex(6)
    connection.settings_dict.setdefault("TEST", {})["NAME"] = test_name
    report = {"scope": __doc__, "caps": sample["caps"], "warmupRuns": 1, "measuredRuns": 3,
              "backgroundRowsPerProvider": 2000, "concurrentLoad": False, "externalCalls": False,
              "liveLimitsChanged": False, "cases": [], "workbooks": sample["workbooks"]}
    def checkpoint():
        progress.write_text(json.dumps({**report, "inProgress": True}, ensure_ascii=False, indent=2))
    created = False
    try:
        connection.creation.create_test_db(verbosity=0, autoclobber=False, serialize=False)
        created = True
        sources, releases = {}, {}
        entities, specs, identity_proofs = {}, [], {}
        for workbook in sample["workbooks"]:
            provider = workbook["provider"]
            sources[provider] = DataSource.objects.create(slug=f"cap-benchmark-{provider}", name=f"TEMP serial cap benchmark {provider}",
                configuration={"connector": "sqlite-herb-compound-target", "targetCellMode": "single"})
            releases[provider] = SourceRelease.objects.create(source=sources[provider], version="temporary-cap-benchmark",
                checksum_sha256=workbook["sha256"], metadata={"connector": "sqlite-herb-compound-target", "benchmarkOnly": True})
        for row in sample["rows"]:
            provider = row["provider"]
            incoming = ("herb", row["row"], *row["values"])
            if row["record"] is not None:
                incoming += (row["record"],)
            payloads, edges = _row_entities_and_relations(sources[provider], incoming)
            for payload in payloads:
                check_identity_consistency(payload, identity_proofs)
                entities[payload["stable_id"]] = KnowledgeEntity(**payload, source_release=releases[provider])
            specs.extend((provider, spec, row["values"][0]) for spec in edges)
        KnowledgeEntity.objects.bulk_create(entities.values(), batch_size=500)
        ids = dict(KnowledgeEntity.objects.values_list("stable_id", "pk"))
        edge_objects = []
        for provider, spec, herb in specs:
            kind, subject, object_, record_id, row_id, metadata = spec
            edge_objects.append(EvidenceRelation(source_release=releases[provider], subject_id=ids[subject], object_id=ids[object_],
                relation_type=kind, source_record_id=record_id, evidence_type=EVIDENCE_TYPE,
                evidence_text=f"Imported from SQLite rowid {row_id}",
                metadata={"sourceRowId": row_id, "source": sources[provider].slug, **metadata}))
        EvidenceRelation.objects.bulk_create(edge_objects, batch_size=500)
        expected = {}
        for (provider, spec, herb), edge in zip(specs, edge_objects):
            key = (provider, herb)
            state = expected.setdefault(key, {"edges": set(), "targets": set()})
            state["edges"].add(edge.pk)
            if spec[0] == "targets":
                state["targets"].add(spec[2])
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE " + connection.ops.quote_name(KnowledgeEntity._meta.db_table))
            cursor.execute("ANALYZE " + connection.ops.quote_name(EvidenceRelation._meta.db_table))
            cursor.execute("SET statement_timeout = '15s'")
        report["temporaryData"] = {"sourceRows": len(sample["rows"]), "entities": len(entities), "edges": len(edge_objects)}
        cases = list(sample["cases"])
        combined_names = list(dict.fromkeys(case["herb"] for case in cases))
        # Name-based production lookup also finds another source's same-name
        # herb in the bounded background. The oracle must include those real
        # rows, rather than misclassifying them as foreign evidence.
        combined_keys = [key for key in expected if key[1] in combined_names]
        combined_edges = set().union(*(expected[key]["edges"] for key in combined_keys))
        combined_targets = set().union(*(expected[key]["targets"] for key in combined_keys))
        cases.append({"provider": "both", "herb": "、".join(combined_names), "stratum": "combined-names-within-sampled-catalogue",
                      "sourceHerbKeys": len(combined_keys), "nameCount": len(combined_names),
                      "rawTripleRows": len(combined_edges)//2, "sourceTargets": len(combined_targets)})
        for case_index, case in enumerate(cases):
            provider = case["provider"]
            DataSource.objects.update(enabled=False)
            enabled = list(sources.values()) if provider == "both" else [sources[provider]]
            DataSource.objects.filter(pk__in=[source.pk for source in enabled]).update(enabled=True)
            oracle = {"edges": combined_edges, "targets": combined_targets} if provider == "both" else expected[(provider, case["herb"])]
            assert len(oracle["edges"]) == case["rawTripleRows"]*2 and len(oracle["targets"]) == case["sourceTargets"]
            kinds = ["network"] if provider == "both" else ["batch", "network"]
            for kind in kinds:
                def invoke(cap):
                    captured = {}
                    started = time.perf_counter()
                    if kind == "batch":
                        original = herb_evidence._visible_relations
                        def capped(**kwargs):
                            return original(**{**kwargs, "limit": cap})
                        with patch.object(herb_evidence, "_visible_relations", side_effect=capped):
                            value = herb_evidence.batch_herb_component_evidence(query_type="herb", queries=[case["herb"]])
                        page = value["results"][0]
                        actual_edges = {edge["id"] for edge in page["relations"]}
                        actual_targets = {target["stableId"] for target in page["targets"]}
                        partial = page["truncated"]
                        raw_partial, raw_rows = None, None
                    else:
                        original = network_pharmacology._relation_query
                        def traced(**kwargs):
                            rows = original(**kwargs)
                            if kwargs.get("herb_relations") is not None:
                                captured["targets"] = rows[:cap]
                            elif kwargs["relation_types"] == network_pharmacology.HERB_COMPOUND_TYPES:
                                captured["herbs"] = rows[:cap]
                            return rows
                        with patch.object(network_pharmacology, "_relation_query", side_effect=traced):
                            value = network_pharmacology.build_network_pharmacology(user=None, herb_query=case["herb"],
                                disease_query="NO_MATCH_CAP_BENCHMARK", row_limit=cap, persist=False)
                        actual_edges = {edge.pk for group in captured.values() for edge in group}
                        actual_targets = {edge.object.stable_id for edge in captured.get("targets", [])}
                        assert value["summary"]["herbTargetCount"] == len(actual_targets)
                        partial = any(value["rawLimits"]["inputRelationsTruncated"].values())
                        raw_partial = value["rawLimits"]["tablesTruncated"]["herbLinks"]
                        raw_rows = len(value["raw"]["herbLinks"])
                    query_ms = (time.perf_counter()-started)*1000
                    serialization_started = time.perf_counter()
                    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
                    serialization_ms = (time.perf_counter()-serialization_started)*1000
                    assert actual_edges <= oracle["edges"] and actual_targets <= oracle["targets"], "Unexpected foreign source evidence."
                    return {"queryMs": query_ms, "serializationMs": serialization_ms, "totalMs": query_ms+serialization_ms,
                            "responseBytes": len(body), "returnedSourceRelations": len(actual_edges), "returnedTargets": len(actual_targets),
                            "evidenceCoverage": len(actual_edges)/len(oracle["edges"]), "targetCoverage": len(actual_targets)/len(oracle["targets"]),
                            "completeInput": actual_edges == oracle["edges"] and actual_targets == oracle["targets"],
                            "inputTruncated": partial, "rawHerbRows": raw_rows, "rawHerbTableTruncated": raw_partial}
                baseline = invoke(24000)
                assert baseline["completeInput"] and not baseline["inputTruncated"], "Baseline must include all selected rows."
                cap_order = list(sample["caps"])
                random.Random(20261021+case_index).shuffle(cap_order)
                measurements = []
                for cap in cap_order:
                    invoke(cap)  # one unmeasured warm-up
                    runs = [invoke(cap) for _ in range(3)]
                    assert len({(row["returnedSourceRelations"],row["returnedTargets"],row["inputTruncated"]) for row in runs}) == 1
                    representative = dict(sorted(runs, key=lambda row: row["totalMs"])[1])
                    representative.update(cap=cap, medianQueryMs=statistics.median(row["queryMs"] for row in runs),
                        medianTotalMs=statistics.median(row["totalMs"] for row in runs), minTotalMs=min(row["totalMs"] for row in runs),
                        maxTotalMs=max(row["totalMs"] for row in runs))
                    measurements.append(representative)
                    print(json.dumps({"provider":provider,"herb":case["herb"],"kind":kind,"cap":cap,"complete":representative["completeInput"],
                                      "medianMs":round(representative["medianTotalMs"],2)} ,ensure_ascii=False),flush=True)
                report["cases"].append({**case, "queryKind": kind, "baseline": baseline,
                                         "measurements": sorted(measurements,key=lambda row:row["cap"])})
                checkpoint()
    finally:
        if created or connection.settings_dict["NAME"] == test_name:
            connection.creation.destroy_test_db(original_name, verbosity=0)
    assert connection.settings_dict["NAME"] == original_name
    after = live_state()
    assert before == after, "Live research/evidence data changed during benchmark."
    report.update(passed=True, temporaryDatabaseDestroyed=True, liveResearchAndEvidenceUnchanged=True,
                  liveStateBefore=before,liveStateAfter=after)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((APP / "var").resolve()) or output.exists() or output.suffix != ".json":
        parser.error("Use a new JSON report under the private var directory.")
    sample = json.loads(args.sample.read_text())
    assert sample["externalCalls"] is False and len(sample["cases"]) == 8
    output.parent.mkdir(parents=True, exist_ok=True)
    progress = output.with_suffix(".progress.json")
    if progress.exists():
        parser.error("Choose a new report path; an earlier progress report already exists.")
    report = run(sample, progress)
    report["sampleSha256"] = hashlib.sha256(args.sample.read_bytes()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"passed":True,"cases":len(report["cases"]),"report":str(output),
                      "temporaryDatabaseDestroyed":True,"liveResearchAndEvidenceUnchanged":True}),flush=True)


if __name__ == "__main__":
    main()
