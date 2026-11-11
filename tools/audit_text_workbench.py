"""Verify frozen main keyword rules and the local text workbench, without models.

Default: read-only catalogue/rule checks. --http additionally retains two named
negative-case tasks and their private exports; a journal prevents duplicates.
Positive source-row cases run in the normal isolated backend tests, not here.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

from postgres_acceptance import APP, ROOT, VAR, environment
from smoke_local_workspace import LocalClient

JOB = APP / "var/text-analysis-business-2026-10-22"
REFERENCE = "078d374852d82ad398e98ff8e97d11f7eb2e3a62"
NODE = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def save(name, value):
    path = JOB / name
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)); temporary.chmod(0o600)
    temporary.replace(path)


def fingerprint(before=None):
    from django.apps import apps
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db import connection, transaction
    from django.db.models import Max
    from apps.core.models import EvidenceRelation
    labels = ["core.AnalysisTask", "core.AnalysisSnapshotRow", "core.ResearchDataset", "core.ResearchDatasetRow",
              "proteomics.ProteomicsRowResult", "core.MedicalCase", "core.MedicalCaseCandidate", "core.VisualizationArtifact",
              "core.DataSource", "core.SourceRelease", "core.KnowledgeEntity", "core.EntityIdentifier"]
    result = {}
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        for label in labels:
            model = apps.get_model(label)
            upper = before[label]["upper"] if before else model.objects.aggregate(value=Max("pk"))["value"] or 0
            checksum, count = hashlib.sha256(), 0
            for row in model.objects.filter(pk__lte=upper).order_by("pk").values().iterator(chunk_size=500):
                plain = json.loads(json.dumps(row, cls=DjangoJSONEncoder))
                checksum.update((canonical(plain) + "\n").encode()); count += 1
            result[label] = {"upper": upper, "count": count, "sha256": checksum.hexdigest()}
        result["relations"] = {"count": EvidenceRelation.objects.count(),
                               "upper": EvidenceRelation.objects.aggregate(value=Max("pk"))["value"]}
    return result


def rule_and_catalogue_checks():
    from django.db import connection, transaction
    from apps.core.models import KnowledgeEntity
    from apps.core.services.text_analysis import build_text_analysis, rank_syndrome_rules
    original = subprocess.run(["git", "show", f"{REFERENCE}:src/lib/analysis.ts"], cwd=ROOT,
                              check=True, capture_output=True).stdout
    assert original == (ROOT / "src/lib/analysis.ts").read_bytes(), "Frozen source differs from reference."
    queries = ["乏力、偏瘫、舌暗、脉涩、中风", "痰、眩晕、麻木、语言不利、苔腻", "头痛、眩晕、急躁、血压、肝阳",
               "手足震颤、口干、失眠、舌红、风动", "眩晕、眩晕", "乏力乏力", "SYNTHETIC_SAMPLE_A12", "", "无乏力", "痰、头痛、口干"]
    # Execute only the frozen rule declaration and score function. No Prisma,
    # old server, model or database query is imported or run.
    script = r'''
const fs=require('node:fs'),vm=require('node:vm');
const root=process.argv[1],ts=require(root+'/web/node_modules/typescript');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const tree=ts.createSourceFile('analysis.ts',input.source,ts.ScriptTarget.Latest,true);
const definitions=tree.statements.filter(node =>
  ts.isVariableStatement(node)&&node.declarationList.declarations.some(item=>item.name.getText(tree)==='syndromeRules')
  || ts.isFunctionDeclaration(node)&&node.name?.text==='scoreRule');
if(definitions.length!==2)throw new Error('Unexpected frozen rule structure');
const code=ts.transpileModule(definitions.map(node=>node.getText(tree)).join('\n'),
 {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const context={queries:input.queries};vm.createContext(context);
vm.runInContext(code+`; output=queries.map(query=>syndromeRules.map(rule=>({name:rule.name,score:scoreRule(query,rule.keywords),matchedKeywords:rule.keywords.filter(keyword=>query.includes(keyword))})).sort((a,b)=>b.score-a.score));`,context,{timeout:1000});
process.stdout.write(JSON.stringify(context.output));
'''
    process = subprocess.run([str(NODE), "-e", script, str(ROOT)],
        input=json.dumps({"source": original.decode(), "queries": queries}), text=True,
        capture_output=True, check=True, timeout=10)
    legacy = json.loads(process.stdout)
    for query, expected in zip(queries, legacy, strict=True):
        assert rank_syndrome_rules(query) == expected, query
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
        counts = {kind: KnowledgeEntity.objects.filter(is_active=True, entity_type=kind).count()
                  for kind in ("syndrome", "formula", "herb")}
        cases = []
        for query in ("乏力、舌暗", "痰、苔腻", "头痛、急躁", "口干、舌红", "SYNTHETIC_SAMPLE_A12"):
            result = build_text_analysis(query)
            if not counts["syndrome"]:
                assert result["matchStatus"] in ("catalog_missing", "no_rule_match") and not result["evidenceRecords"]
                assert not result["evidence"]["formula"] and not result["evidence"]["targets"]
            cases.append({"query": query, "status": result["matchStatus"], "selectedRule": result["selectedRule"],
                          "relations": len(result["evidenceRecords"]), "sources": len(result["sources"])})
    proof = {"frozenRuleCommit": REFERENCE, "ruleSourceSha256": hashlib.sha256(original).hexdigest(),
             "sameInputRuleCases": len(queries), "ruleScoresMatch": True, "catalogueCounts": counts,
             "catalogueCases": cases, "externalCalls": False, "databaseReadOnly": True,
             "clinicalValidation": False}
    save("local-audit.json", proof)
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http", action="store_true"); parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    JOB.mkdir(parents=True, exist_ok=True); JOB.chmod(0o700)
    if (JOB / "http-verified.json").exists():
        raise ValueError("Completed proof exists; do not create duplicate tasks or replace evidence.")
    environment(); sys.path.insert(0, str(APP))
    import django
    django.setup()
    proof = rule_and_catalogue_checks()
    if not args.http:
        print(json.dumps(proof, ensure_ascii=False)); return
    journal = JOB / "http-state.json"
    if journal.exists():
        if not args.resume: raise ValueError("Existing journal requires --resume.")
        state = json.loads(journal.read_text())
    else:
        state = {"before": fingerprint(), "tasks": {}}; save(journal.name, state)
    accounts = json.loads((VAR / "accounts.json").read_text())
    clients = [LocalClient(accounts[key], base_url="http://127.0.0.1:5174", csrf_cookie_name="tcm_pg_csrf")
               for key in ("a", "b", "admin")]
    owner, other, admin = clients; outputs = []
    try:
        for name, query, match in [("catalogue-missing", "乏力、舌暗", "catalog_missing"),
                                   ("no-rule", "SYNTHETIC_SAMPLE_A12", "no_rule_match")]:
            if name not in state["tasks"]:
                _, task = owner.request("/api/v1/research/text-analysis/", method="POST", expected=201,
                    data={"name": f"本地规则验收 {name}（非医案/非诊断）", "query": query, "caseId": None})
                state["tasks"][name] = task["id"]; save(journal.name, state)
            base = f'/api/v1/research/analysis-tasks/{state["tasks"][name]}'
            _, task = owner.request(base + "/"); result = task["result"]
            assert task["status"] == "succeeded" and task["owner_id"] == accounts["a"]["id"]
            assert result["matchStatus"] == match and not result["evidenceRecords"] and not result["sources"]
            assert result["algorithmVersion"] == "text-analysis-main-1.1"
            for format_ in ("csv", "pdf"):
                _, payload = owner.request(base + f"/export/?file_format={format_}")
                path = JOB / f'task-{task["id"]}.{format_}'; path.write_bytes(payload); path.chmod(0o600)
                if format_ == "pdf": assert payload.startswith(b"%PDF-")
                else:
                    rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
                    assert ["query", query] in rows and ["match_status", match] in rows
                    assert any(level == "warning" for level, _ in rows)
                other.request(base + f"/export/?file_format={format_}", expected=404)
            other.request(base + "/", expected=404)
            _, administrator = admin.request(base + "/"); assert administrator["owner_id"] == accounts["a"]["id"]
            _, restored = owner.request(base + "/"); assert restored["result"] == result
            outputs.append({"taskId": task["id"], "matchStatus": match, "relations": 0,
                            "exports": ["csv", "pdf"], "otherOwnerDenied": True, "restoreUnchanged": True})
        after = fingerprint(state["before"]); assert after == state["before"], "Existing research or catalogue changed."
        save("http-verified.json", {"passed": True, "tasks": outputs, "previousRecordsUnchanged": True,
             "newTasks": len(outputs), "externalCalls": False, "medicalCasesCreated": False,
             "positiveCatalogueChainValidated": False})
        print(json.dumps({"passed": True, "sameInputRuleCases": proof["sameInputRuleCases"],
                          "catalogueCounts": proof["catalogueCounts"], "tasks": outputs}, ensure_ascii=False))
    finally:
        for client in clients:
            client.request("/api/v1/auth/session/", method="DELETE", expected=204)


if __name__ == "__main__":
    main()
