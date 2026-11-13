"""Local part of frozen main's scientist_hypothesis, backed by frozen evidence.

Reuses the original input splitting and report sections. Catalogue queries use
the migrated network service's source identities and original-row constraints.
Proposed methods are never described as executed analyses or experiments.
"""
from collections import defaultdict
import re


VERSION = "scientist-local-1"
REFERENCE_COMMIT = "078d374852d82ad398e98ff8e97d11f7eb2e3a62"
REFERENCE_FUNCTION = "backend/data_service.py#scientist_hypothesis"


def parse_formula(value):
    # Frozen main: backend/data_service.py::_parse_formula. Deduplicate only
    # repeated input herb names; this is not a compound/target alias parser.
    return list(dict.fromkeys(part.strip() for part in re.split(r"[,，、;；\n]+", value) if part.strip()))


def build_report(parameters, network, tables):
    summary = network["summary"]
    entities = {row["id"]: row for row in tables["entities"]}
    formula = parameters["formulaHerbs"]
    counts = {
        "disease_target_count": summary["diseaseTargetCount"],
        "formula_target_count": summary["herbTargetCount"],
        "intersection_count": summary["strictIntersectionCount"],
        "direct_association_count": summary["directAssociationTargetCount"],
        "component_count": summary["componentCount"],
    }
    strict = [row for row in tables["targets"] if row["matchType"] == "严格交集"]
    assert len(strict) == counts["intersection_count"]
    identity_merged = any(len(row.get("sourceEntityIds", [])) > 1 for row in tables["targets"])
    authority_verified = bool(tables["targets"]) and all(
        row.get("identityStatus") == "verified" for row in tables["targets"])
    compounds, herb_targets = defaultdict(set), defaultdict(set)
    for row in tables["evidenceRecords"]:
        if row["subjectType"] == "herb" and row["objectType"] == "compound":
            compounds[row["subjectId"]].add(row["objectId"])
    for row in tables["herbLinks"]:
        herb_targets[row["herbStableId"]].add(row["targetStableId"])
    herb_summaries = []
    for entity in sorted(entities.values(), key=lambda row: (row["label"], row["stableId"])):
        if entity["entityType"] != "herb" or entity["label"] not in summary["matchedHerbs"]:
            continue
        herb_summaries.append({"herb": entity["label"], "entityId": entity["id"], "stableId": entity["stableId"],
            "sourceSlug": entity["sourceSlug"], "sourceVersion": entity["sourceVersion"],
            "component_count": len(compounds[entity["id"]]), "target_count": len(herb_targets[entity["stableId"]])})
    references = {}
    for row in [*tables["entities"], *tables["evidenceRecords"]]:
        if row.get("sourceReleaseId"):
            references[row["sourceReleaseId"]] = {key: row[key] for key in (
                "sourceReleaseId", "sourceSlug", "sourceVersion", "sourceChecksumSha256")}
    uncertainties = [
        "本报告为本地来源证据整理和研究计划模板，没有调用模型或执行实验。",
        "已核实的人类规范编号按靶点身份统计，其余记录保持来源实体身份；同名不构成合并依据，严格交集为零不能证明没有共同生物学靶点。",
        "尚未核实的靶点物种和规范编号仍需独立核实；来源声明、名称匹配不等于权威身份确认。",
    ]
    if summary["unmatchedHerbs"]:
        uncertainties.append("未命中的组成输入：" + "、".join(summary["unmatchedHerbs"]))
    if summary["unmatchedDiseases"]:
        uncertainties.append("疾病输入未命中当前启用目录。")
    if summary["unresolvedFormulas"]:
        uncertainties.append("目录中缺少明确组成关系的方剂：" + "、".join(summary["unresolvedFormulas"]))
    if not tables["evidenceRecords"]:
        uncertainties.append("本次没有可用来源关系，不能据此形成有数据支持的机制结论。")
    methods = [
        {"step": "本地疾病与方药证据检索", "status": "completed", "detail": "已保存本次启用来源记录及版本，完整证据由快照提供。"},
        {"step": "来源及规范身份层面的靶点交集", "status": "completed", "detail": "使用同一来源实体或已核实的人类规范编号计算严格交集；直接关联单独列出，原始来源记录保留。"},
        {"step": "物种与权威编号核实", "status": "pending", "detail": "需要可追溯的权威参考版本和人工核对。"},
        {"step": "ChEMBL 活性补强", "status": "not_run", "detail": "本次未请求外部活性数据。"},
        {"step": "GO/KEGG、Reactome 或 STRING 分析", "status": "not_run", "detail": "本次没有执行富集或 PPI。"},
        {"step": "文献检索、模型增强及实验验证", "status": "not_run", "detail": "需要另行接入或实验设计，不生成论文引用或实验结果。"},
    ]
    disease, question = parameters["disease"], parameters["question"]
    title = f"{'、'.join(formula)}与{disease}的本地来源证据及研究计划"
    abstract = (
        f"围绕“{question}”整理本地目录。疾病侧有 {counts['disease_target_count']} 个靶点身份，"
        f"方药侧有 {counts['formula_target_count']} 个靶点身份、{counts['component_count']} 个来源成分记录；"
        f"同一实体身份严格交集 {counts['intersection_count']} 个，直接关联 {counts['direct_association_count']} 个。"
        "这些是目录记录统计，不是实验结果或机制验证；未执行模型、外部检索、富集或实验。"
    )
    result = {
        "analysisKind": "scientist_hypothesis", "algorithmVersion": VERSION,
        "legacyReference": {"commit": REFERENCE_COMMIT, "function": REFERENCE_FUNCTION},
        "input": {"question": question, "disease": disease, "formula": formula, "focus": parameters["focus"]},
        "problem_statement": f"需核对当前资料能否支持方药与疾病的关联；未查询的资料和未完成的步骤单独保留。",
        "paper_title": title, "paper_abstract": abstract,
        "rationale": [f"疾病查询展开：{'、'.join(summary['expandedDiseaseQueries'])}，按当前明确别名配置检索。",
                      f"实际命中 {len(herb_summaries)} 个中药来源实体，逐来源统计，不按同名归并。",
                      f"严格交集 {counts['intersection_count']} 个；没有交集时不以其他方药靶点回填共同靶点。"],
        "technical_details": ["版本化本地目录", "原行来源约束", "来源实体身份隔离", "完整证据快照"],
        "datasets": {"source": [references[key] for key in sorted(references)], "experimentalMeasurements": False},
        "methods": methods,
        "experiments": {"status": "not_run", "validation": "实验验证需研究者另行设计和执行，本报告不产生实验结果。"},
        "results": {**counts, "top_intersection_targets": [row["target"] for row in strict[:30]],
                    "top_intersection_records": strict[:30], "intersection_display_truncated": len(strict) > 30,
                    "representative_components": [row["label"] for row in sorted(entities.values(), key=lambda r: r["stableId"])
                                                  if row["entityType"] == "compound"][:30]},
        "evidence": {"herb_summaries": herb_summaries, "relationCount": len(tables["evidenceRecords"])},
        "references": [references[key] for key in sorted(references)],
        "uncertainties": uncertainties, "model": None, "externalCalls": False,
        "identityMerged": identity_merged, "authorityIdentityVerified": authority_verified,
        "identityVerificationScope": "candidate_targets",
        "identityReferenceReleaseId": network.get("targetIdentity", {}).get("releaseId"),
        "summary": {"question": question, "disease": disease, **counts},
        "networkSummary": summary,
    }
    tables["herbSummaries"] = herb_summaries
    tables["reportSections"] = [{"section": key, "content": result[key]} for key in (
        "input", "problem_statement", "paper_title", "paper_abstract", "rationale", "technical_details",
        "datasets", "methods", "experiments", "results", "references", "uncertainties")]
    return result, tables
