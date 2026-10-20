"""Read-only main/current result and identity audit of the local HIT sample.

extract: bundled Python reads the workbook and executes frozen main functions.
compare: project Python checks the isolated PostgreSQL catalogue, without writes.
Source identity assertions are not certified biological identities.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
VAR = ROOT / "python_app/var/postgres-acceptance"
REFERENCE = "078d374852d82ad398e98ff8e97d11f7eb2e3a62"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(workbook):
    import openpyxl
    import pandas as pd
    sys.path.insert(0, str(ROOT))
    from backend import data_service as main
    frozen = subprocess.check_output(["git", "show", f"{REFERENCE}:backend/data_service.py"], cwd=ROOT)
    assert frozen == (ROOT / "backend/data_service.py").read_bytes(), "Main reference file changed."
    before = digest(workbook)
    book = openpyxl.load_workbook(workbook, read_only=True, data_only=False)
    try:
        sheet = book.active
        header = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        rows = []
        for cells in sheet.iter_rows(min_row=2, max_row=101):
            assert not any(cell.data_type == "f" for cell in cells), "Review formulas separately."
            rows.append({"sourceRow": cells[0].row, "raw": dict(zip(header, [cell.value for cell in cells]))})
        sheet_name = sheet.title
    finally:
        book.close()
    assert before == digest(workbook) and len(rows) == 100
    frame = pd.DataFrame([row["raw"] for row in rows])
    def source_frame(provider):
        return frame if provider == "hit" else pd.DataFrame(columns=main.SOURCE_FILES[provider]["columns"])
    calls = []
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE herb_component_target(source, herb, component, target)")
        connection.executemany("INSERT INTO herb_component_target VALUES(?,?,?,?)", [
            ("hit", row["raw"]["Chinese Character"], row["raw"]["Compound Name"], row["raw"]["Symbol"]) for row in rows])
        for query_type, column, function in [("herb", "Chinese Character", main.search_herb), ("compound", "Compound Name", main.search_component)]:
            queries = list(dict.fromkeys(row["raw"][column] for row in rows)) + ["NO_MATCH_SYNTHETIC"]
            for query in queries:
                with patch.object(main, "_cache", return_value=None), patch.object(main, "load_source", side_effect=source_frame):
                    excel = function(query, limit=10000)
                with patch.object(main, "_cache", return_value=connection):
                    cached = function(query, limit=10000)
                calls.append({"queryType": query_type, "query": query, "mainExcel": excel, "mainCache": cached})
    return {"referenceCommit": REFERENCE, "referenceSha256": hashlib.sha256(frozen).hexdigest(),
            "workbook": str(workbook), "workbookSha256": before, "sheet": sheet_name, "rows": rows, "queries": calls,
            "scope": "100 historical source rows; no authoritative species/reference release"}


def compare(extracted, proteomics):
    from postgres_acceptance import APP, environment
    environment(); sys.path.insert(0, str(APP))
    import django
    django.setup()
    from django.db import connection, transaction
    from apps.core.models import DataSource, EntityIdentifier, EvidenceRelation, KnowledgeEntity
    from apps.core.services.herb_evidence import batch_herb_component_evidence
    from apps.core.services.network_pharmacology import build_network_pharmacology
    from apps.proteomics.services import _parse_rows, resolve_mapping
    from apps.sources.connectors.uniprot import _ACCESSION, UniProtCatalogSnapshot, UniProtProtein
    from apps.sources.uniprot_identity import build_identity_plan
    assert connection.vendor == "postgresql" and connection.settings_dict["NAME"] == "tcm_acceptance"
    sample = json.loads(extracted.read_text())
    assert digest(Path(sample["workbook"])) == sample["workbookSha256"]
    rows = sample["rows"]
    queries, issues, intended = [], [], []
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
        source = DataSource.objects.get(configuration__databaseFile="hit-identity-first100.sqlite3")
        entities = list(KnowledgeEntity.objects.filter(source_release__source=source, is_active=True).select_related("source_release"))
        relations = list(EvidenceRelation.objects.filter(source_release__source=source, is_active=True).select_related("subject", "object"))
        raw_by_row = {row["sourceRow"]: row["raw"] for row in rows}
        actual_proofs = []
        for edge in relations:
            metadata = edge.metadata
            row_id = metadata.get("sourceOrigin", {}).get("sourceRow")
            if (metadata.get("rawFields") != raw_by_row.get(row_id)
                    or metadata.get("sourceOrigin", {}).get("workbookSha256") != sample["workbookSha256"]):
                issues.append({"kind": "raw_source_mismatch", "evidenceId": edge.pk})
            actual_proofs.append((row_id, edge.relation_type, edge.subject.metadata.get("sourceEntityId"), edge.object.metadata.get("sourceEntityId")))
        expected_proofs = []
        for row in rows:
            raw = row["raw"]
            expected_proofs += [(row["sourceRow"], "contains", raw["Herb ID"], raw["Compound Id"]),
                                (row["sourceRow"], "targets", raw["Compound Id"], raw["Target ID"])]
        if Counter(actual_proofs) != Counter(expected_proofs):
            issues.append({"kind": "source_edge_identity_mismatch"})
        for call in sample["queries"]:
            kind, query = call["queryType"], call["query"]
            page = batch_herb_component_evidence(query_type=kind, queries=[query])["results"][0]
            column = "Chinese Character" if kind == "herb" else "Compound Name"
            selected = [row for row in rows if row["raw"][column].casefold() == query.casefold()]
            expected_targets = {row["raw"]["Target ID"] for row in selected}
            actual_targets = {row["sourceEntityId"] for row in page["targets"]}
            row_ids = {row["sourceRow"] for row in selected}
            expected_edges = {proof for proof in expected_proofs if proof[0] in row_ids}
            actual_edges = {(r["sourceOrigin"]["sourceRow"], r["relationType"],
                             r["sourceIdentity"]["herbId"] if r["relationType"] == "contains" else r["sourceIdentity"]["compoundId"],
                             r["sourceIdentity"]["compoundId"] if r["relationType"] == "contains" else r["sourceIdentity"]["targetId"])
                            for r in page["relations"]}
            exact = actual_targets == expected_targets and actual_edges == expected_edges and not page["truncated"]
            if not exact:
                issues.append({"kind": "query_source_scope_mismatch", "query": query})
            labels = {r["label"] for r in page["targets"]}
            main_labels = set(call["mainCache"]["targets"])
            fuzzy = [row for row in rows if query.casefold() in row["raw"][column].casefold()]
            main_expected = Counter((row["raw"]["Chinese Character"],row["raw"]["Compound Name"],row["raw"]["Symbol"]) for row in fuzzy)
            branch_proofs = [Counter((link["herb"],link["component"],target) for link in call[branch]["links"] for target in link["targets"])
                             for branch in ("mainExcel","mainCache")]
            main_rows_checked = all(proofs == main_expected for proofs in branch_proofs)
            if not main_rows_checked:
                issues.append({"kind":"main_branch_row_projection_mismatch","query":query})
            differs = labels != main_labels or len(selected) != len(call["mainCache"]["links"])
            if len(fuzzy) == len(selected) and (labels != main_labels or labels != set(call["mainExcel"]["targets"])):
                issues.append({"kind":"unexplained_main_target_difference","query":query})
            if differs:
                intended.append({"query": query, "reason": "main substring search versus current exact entity search",
                                 "mainRows": len(call["mainCache"]["links"]), "currentSourceRows": len(selected)})
            if kind == "herb":
                network = build_network_pharmacology(user=None, herb_query=query, disease_query="NO_MATCH_SYNTHETIC", persist=False)
                proofs = {(r["herbSourceRecordId"].split(":")[1], r["sourceRecordId"].split(":")[1]) for r in network["raw"]["herbLinks"]}
                if (network["summary"]["herbTargetCount"] != len(expected_targets)
                        or len(network["raw"]["herbLinks"]) != len(selected) or any(a != b for a,b in proofs)):
                    issues.append({"kind": "network_scope_mismatch", "query": query})
            queries.append({"queryType": kind, "query": query, "exactSourceRecordsMatch": exact,
                            "currentTargets": len(actual_targets), "currentSourceRows": len(selected),
                            "mainExcelTargets": call["mainExcel"]["counts"]["targets"], "mainCacheTargets": len(main_labels),
                            "mainSearchSemanticsDiffer": differs, "mainBothBranchesSourceRowsMatch":main_rows_checked})
        proteins = [e for e in entities if e.entity_type == "protein"]
        names, accessions = defaultdict(set), defaultdict(set)
        identity_rows = []
        for entity in proteins:
            metadata = entity.metadata
            names[entity.label.casefold()].add(metadata["sourceEntityId"])
            refs = [r["identifier"] for r in metadata.get("sourceReferences", []) if r.get("namespace") == "uniprot"]
            for accession in refs:
                accessions[accession].add(metadata["sourceEntityId"])
            identity_rows.append({"entityId": entity.pk, "sourceEntityId": metadata["sourceEntityId"], "symbol": metadata.get("symbol"),
                                  "organism": entity.organism, "sourceReportedAccessions": refs,
                                  "accessionSyntaxValid": bool(refs) and all(_ACCESSION.fullmatch(x) for x in refs),
                                  "status": "authority_and_species_not_verified"})
        promoted = EntityIdentifier.objects.filter(entity_id__in=[e.pk for e in proteins], is_active=True).count()
        if promoted or any(e.organism or e.metadata.get("identifierStatus") != "unverified_symbol" for e in proteins):
            issues.append({"kind": "unsupported_canonical_identity_claim"})
        identity = {"targetCount": len(proteins), "unknownSpecies": sum(not e.organism for e in proteins),
                    "validAccessionSyntax": sum(r["accessionSyntaxValid"] for r in identity_rows), "canonicalIdentifiers": promoted,
                    "sameNameDifferentIds": {k: sorted(v) for k,v in names.items() if len(v)>1},
                    "accessionMultiOwners": {k: sorted(v) for k,v in accessions.items() if len(v)>1}, "rows": identity_rows,
                    "biologicalIdentityVerified": False, "reason": "No authoritative offline species/accession release is available."}
        # Synthetic planning probe: a same-symbol human assertion must not
        # silently absorb these unknown-species source entities. No import/apply.
        probe = UniProtCatalogSnapshot(proteins=tuple(UniProtProtein(accession=r["sourceReportedAccessions"][0],
            protein_name="SYNTHETIC GUARD PROBE", primary_gene=r["symbol"], gene_names=()) for r in identity_rows),
            source_version="SYNTHETIC-OFFLINE-PROBE", source_release_date=None, checksum_sha256="0"*64,
            total_results=len(identity_rows), page_count=1)
        plan = build_identity_plan(DataSource(pk=-1,slug="synthetic-offline-probe"), probe)
        identity["syntheticGuardProbe"] = {"notAuthoritativeData":True,"mappedToExisting":len(plan.local_entities),
                                           "excludedUnknownSpecies":plan.summary["unknownSpeciesLocalTargets"]}
        if plan.local_entities:
            issues.append({"kind":"unknown_species_silently_associated_by_symbol"})
    numeric = []
    for case in json.loads(proteomics.read_text())["cases"]:
        mapping = resolve_mapping(list(case["rows"][0]), {})
        analyzed, qc = _parse_rows(case["rows"], mapping, case["thresholds"])
        selected = [row.row_index for row in analyzed if row.selected]
        equal = selected == case["mainSelectedIndices"]
        values_equal = [(row.row_index, row.log2_fold_change, row.p_value, row.fdr) for row in analyzed] == [
            (row["index"], row["log2FoldChange"], row["pValue"], row["fdr"]) for row in case["mainParsedRows"]]
        if case["policy"] == "equal":
            expected = equal and values_equal
        elif case["policy"] == "intentional_keep_qc_row":
            expected = equal and not selected and len(analyzed) == 1 and not case["mainParsedRows"]
        else:
            expected = not equal and not selected
        if not expected:
            issues.append({"kind": "unexplained_proteomics_difference", "case": case["name"]})
        numeric.append({"case": case["name"], "policy": case["policy"], "mainSelected": case["mainSelectedIndices"],
                        "currentSelected": selected, "numericValuesMatch": values_equal, "expectedBehavior": expected, "qc": qc})
    return {"passed": not issues, "referenceCommit": sample["referenceCommit"], "sourceRows": len(rows),
            "referenceSha256": sample["referenceSha256"], "activeEntities": len(entities), "sourceRelations": len(relations),
            "queries": queries, "intentionalDifferences": intended, "identity": identity, "proteomics": numeric,
            "issues": issues, "catalogueTransactionReadOnly": True, "externalCalls": False,
            "scope": "bounded source/algorithm consistency; not experimental or authoritative biological validation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    command = sub.add_parser("extract"); command.add_argument("workbook", type=Path)
    command = sub.add_parser("compare"); command.add_argument("sample", type=Path); command.add_argument("proteomics", type=Path)
    for command in sub.choices.values():
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    destination = args.output.resolve()
    if not destination.is_relative_to(VAR.resolve()) or destination.suffix != ".json" or destination.exists():
        parser.error("Use a new JSON report under the private acceptance directory; never overwrite evidence.")
    result = extract(args.workbook.resolve()) if args.action == "extract" else compare(args.sample, args.proteomics)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in {"rows","queries","identity","proteomics"}},ensure_ascii=False))
    if result.get("passed") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
