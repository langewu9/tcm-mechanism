"""Build a bounded, de-identified graph from explicit case-workbook fields."""

from __future__ import annotations

import hashlib
import re

from .case_analysis_figures import DOSE, NAME


MAX_GRAPH_VISITS = 1_000
MAX_GRAPH_NODES = 15_000
MAX_GRAPH_EDGES = 50_000

ENTITY_LABELS = {
    "case": "病例",
    "visit": "诊次",
    "western_diagnosis": "西医病名",
    "tcm_diagnosis": "中医病名",
    "syndrome": "证型",
    "treatment": "治法治则",
    "tongue": "舌象",
    "pulse": "脉象",
    "prescription": "方药记录",
    "formula": "方剂",
    "herb": "药物",
}

RELATION_LABELS = {
    "has_visit": "包含诊次",
    "records_western_diagnosis": "记录西医病名",
    "records_tcm_diagnosis": "记录中医病名",
    "records_syndrome": "记录证型",
    "records_treatment": "记录治法治则",
    "records_tongue": "记录舌象",
    "records_pulse": "记录脉象",
    "has_prescription": "记录方药",
    "mentions_formula": "明确提及方剂",
    "contains_herb": "明确列出药物",
}


def _term_id(kind: str, label: str) -> str:
    digest = hashlib.sha256(f"{kind}\0{label}".encode("utf-8")).hexdigest()[:20]
    return f"{kind}:{digest}"


def _evidence(sheet: str, row_number: int, field: str, value=None):
    item = {"sheet": sheet, "row": row_number, "field": field}
    if value:
        item["value"] = value
    return item


def _herb_dose_details(text: str | None, recognized: list[str]) -> dict[str, dict[str, str]]:
    """Attach a recorded dose/preparation fragment to recognized herb names."""
    if not text or not recognized:
        return {}
    recognized_set = set(recognized)
    details: dict[str, dict[str, str]] = {}
    for part in re.split(r"[,，;；。\n]", text):
        matches = list(DOSE.finditer(part))
        previous_end = 0
        for dose in matches:
            name_text = part[previous_end:dose.start()]
            previous_end = dose.end()
            name_text = re.sub(r"[（(][^）)]*[）)]", " ", name_text)
            name_text = re.sub(r"^(?:方药|药物|组成|处方)[：:]?", "", name_text.strip())
            name_text = re.sub(r"^(?:先煎|后下|后入|包煎|冲服|另煎|烊化)+", "", name_text)
            candidates = [re.sub(r"各$", "", value.strip()) for value in re.split(r"[、＋+/]", name_text)]
            preparation = "、".join(re.findall(r"先煎|后下|后入|包煎|冲服|另煎|烊化", part))
            dose_text = re.sub(r"各", "", dose.group()).strip()
            for name in candidates:
                if NAME.fullmatch(name) and name in recognized_set:
                    details[name] = {"dose": dose_text, **({"preparation": preparation} if preparation else {})}
    return details


def build_case_knowledge_graph(records: list[dict], sheet_name: str) -> dict:
    """Return only structured entities, relationships and row-level provenance.

    Original workbook identifiers, names, addresses, occupations and narrative
    fields are used neither as labels nor as stored evidence.
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_counter = 0
    included: list[dict] = []
    included_case_ids: set[str] = set()
    case_ids: dict[str, str] = {}
    visit_number = 0

    def ensure_term(kind: str, label: str, properties=None, evidence=None, stable_id=None):
        node_id = stable_id or _term_id(kind, label)
        node = nodes.get(node_id)
        if node is None:
            node = {"id": node_id, "type": kind, "typeLabel": ENTITY_LABELS[kind], "label": label,
                    "properties": {}, "evidence": []}
            nodes[node_id] = node
        if properties:
            for key, value in properties.items():
                if value is not None:
                    node["properties"].setdefault(key, value)
        if evidence and evidence not in node["evidence"]:
            node["evidence"].append(evidence)
        return node_id

    def add_edge(source: str, target: str, relation: str, properties=None, evidence=None):
        nonlocal edge_counter
        edge_counter += 1
        edges.append({"id": f"relation:{edge_counter:05d}", "source": source, "target": target,
                      "type": relation, "label": RELATION_LABELS[relation],
                      "properties": properties or {}, "evidence": [evidence] if evidence else []})

    for record in records:
        if visit_number >= MAX_GRAPH_VISITS:
            break
        concepts = [(kind, record.get(key), relation, field) for key, kind, relation, field in (
            ("western_diagnosis", "western_diagnosis", "records_western_diagnosis", "西医病名"),
            ("tcm_diagnosis", "tcm_diagnosis", "records_tcm_diagnosis", "中医病名"),
            ("syndrome", "syndrome", "records_syndrome", "证型"),
            ("treatment", "treatment", "records_treatment", "治法治则"),
            ("tongue", "tongue", "records_tongue", "舌象"),
            ("pulse", "pulse", "records_pulse", "脉象"),
        ) if record.get(key)]
        formulas = record.get("formulas", [])
        herbs = record.get("herbs", [])
        has_prescription = bool(formulas or herbs)

        # Do not leave a partially represented visit if a configured bound is met.
        candidate_labels = {(kind, label) for kind, label, _, _ in concepts}
        candidate_labels.update(("formula", label) for label in formulas)
        candidate_labels.update(("herb", label) for label in herbs)
        new_nodes = sum(1 for kind, label in candidate_labels if _term_id(kind, label) not in nodes)
        group_key = record["case_group"]
        is_new_case = group_key not in case_ids
        needed_nodes = new_nodes + 1 + int(is_new_case) + int(has_prescription)
        needed_edges = 1 + len(concepts) + int(has_prescription) + len(formulas) + len(herbs)
        if len(nodes) + needed_nodes > MAX_GRAPH_NODES or len(edges) + needed_edges > MAX_GRAPH_EDGES:
            break

        visit_number += 1
        row_number = record["source_row"]
        if is_new_case:
            case_id = f"case:{len(case_ids) + 1:04d}"
            case_ids[group_key] = case_id
        else:
            case_id = case_ids[group_key]
        case_label = f"病例 {int(case_id.split(':')[1]):04d}"
        case_evidence = _evidence(sheet_name, row_number, "病例组")
        case_node = ensure_term("case", case_label,
                                {"性别": record.get("sex"), "年龄分组": record.get("age")},
                                case_evidence, case_id)
        visit_id = f"visit:{visit_number:05d}"
        visit_label = f"第 {record['ordinal']} 诊 · 表格第 {row_number} 行"
        visit_node = ensure_term("visit", visit_label, {"诊次序号": record["ordinal"], "来源行": row_number},
                                 _evidence(sheet_name, row_number, "诊次"), visit_id)
        add_edge(case_node, visit_node, "has_visit", evidence=_evidence(sheet_name, row_number, "诊次"))

        for kind, label, relation, field in concepts:
            entity_id = ensure_term(kind, label, evidence=_evidence(sheet_name, row_number, field, label))
            add_edge(visit_node, entity_id, relation, evidence=_evidence(sheet_name, row_number, field, label))

        if has_prescription:
            prescription_id = f"prescription:{visit_number:05d}"
            prescription_node = ensure_term("prescription", "本诊方药记录",
                                            evidence=_evidence(sheet_name, row_number, "方药（含剂量）"),
                                            stable_id=prescription_id)
            add_edge(visit_node, prescription_node, "has_prescription",
                     evidence=_evidence(sheet_name, row_number, "方药（含剂量）"))
            for formula in formulas:
                formula_id = ensure_term("formula", formula,
                                         evidence=_evidence(sheet_name, row_number, "处方", formula))
                add_edge(prescription_node, formula_id, "mentions_formula",
                         evidence=_evidence(sheet_name, row_number, "处方", formula))
            doses = _herb_dose_details(record.get("prescription_text"), herbs)
            for herb in herbs:
                herb_id = ensure_term("herb", herb,
                                      evidence=_evidence(sheet_name, row_number, "方药（含剂量）", herb))
                properties = doses.get(herb, {})
                evidence_value = herb
                if properties.get("dose"):
                    evidence_value += f" {properties['dose']}"
                add_edge(prescription_node, herb_id, "contains_herb", properties,
                         _evidence(sheet_name, row_number, "方药（含剂量）", evidence_value))

        included.append(record)
        included_case_ids.add(group_key)

    return {
        "schemaVersion": "case-knowledge-graph-v1",
        "scope": "all_visits",
        "scopeLabel": "本工作簿全部诊次",
        "sourceSheet": sheet_name,
        "sourceVisitCount": len(records),
        "includedVisitCount": len(included),
        "omittedVisitCount": len(records) - len(included),
        "caseCount": len(included_case_ids),
        "entityCount": len(nodes),
        "relationshipCount": len(edges),
        "limits": {"maxVisits": MAX_GRAPH_VISITS, "maxEntities": MAX_GRAPH_NODES, "maxRelationships": MAX_GRAPH_EDGES},
        "nodes": list(nodes.values()),
        "edges": edges,
    }
