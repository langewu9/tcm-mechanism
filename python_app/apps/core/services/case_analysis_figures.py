"""Case-specific figures from explicit structured fields, without patient data."""
from collections import Counter
from itertools import combinations
import re


# Only the completed herb/dose column is parsed. Narrative prescriptions and
# missing follow-ups are never used to infer or inherit a previous treatment.
DOSE = re.compile(r"(?:各\s*)?\d+(?:\.\d+)?\s*(?:～|~|—|-)?\s*\d*(?:\.\d+)?\s*(?:[gG克]|毫克|mg|枚|条|片|钱|两|个|只|粒|支)")
NAME = re.compile(r"^[\u4e00-\u9fff]{1,12}$")


def prescription_herbs(value):
    if not value or value in {"未提及", "未注明"}:
        return []
    herbs = set()
    pending = []
    for part in re.split(r"[，,;；。\n]", value):
        part = re.sub(r"[（(][^）)]*[）)]", "", part).strip()
        dose = DOSE.search(part)
        if not dose:
            # A bare name is counted only if the following fragment explicitly
            # assigns a shared dose (e.g. 川牛膝、怀牛膝各10g).
            pending = [name.strip() for name in part.split("、") if NAME.fullmatch(name.strip())]
            continue
        names = part[:dose.start()].strip()
        names = re.sub(r"(?:先煎|后下|后入|包煎|冲服|另煎|烊化)$", "", names)
        names = re.sub(r"^(?:方药[：:]?|药物[：:]?)", "", names)
        candidates = names.split("、")
        if "各" in dose.group():
            candidates = pending + candidates
        for name in candidates:
            name = name.strip()
            if NAME.fullmatch(name):
                herbs.add(name)
        pending = []
    return sorted(herbs)


def formula_names(value):
    if not value or value == "未提及":
        return []
    # This is an explicit name mention, not recognition of a formula from herbs.
    text = re.sub(r"^(?:方用|方选|选用|给予|予|处方[：:]?)", "", value)
    return sorted(set(re.findall(r"[\u4e00-\u9fff]{2,12}(?:汤|丸|散|饮)(?=合|加|减|化|[，,。；;\s]|$)", text)))


def _rows(counter):
    return [{"label": label, "count": count} for label, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


def _graph(pairs, node_types, title, subtitle, directed=False):
    chosen, seen = [], set()
    for a, b, count in pairs:
        if len(seen | {a, b}) <= 80:
            chosen.append((a, b, count))
            seen.update((a, b))
        if len(chosen) == 60:
            break
    ids, degrees = {}, Counter()
    for a, b, _ in chosen:
        for key in (a, b):
            ids.setdefault(key, f"n{len(ids) + 1}")
        degrees[a] += 1
        degrees[b] += 1
    max_count = max((count for _, _, count in chosen), default=1)
    return {"chartType": "network", "title": title, "subtitle": subtitle, "layout": "circular",
            "caseGraph": True, "directed": directed,
            "data": [{"id": id_, "label": label, "type": node_types.get(label, "herb"), "degree": degrees[label]}
                     for label, id_ in ids.items()],
            "edges": [{"source": ids[a], "target": ids[b], "score": count / max_count, "cooccurrence": count, "evidence": []} for a, b, count in chosen]}


def build_case_figures(records, unit_label):
    """Return aggregate matrices/graphs only, discarding row identity and text."""
    transactions = [set(row["herbs"]) for row in records]
    herb_counts = Counter(herb for herbs in transactions for herb in herbs)
    n = len(records)
    prescription_count = sum(bool(herbs) for herbs in transactions)
    prefix = f"{unit_label} · {n} 个统计单位"
    pairs = Counter(pair for herbs in transactions for pair in combinations(sorted(herbs), 2))
    formula_counts = Counter(name for row in records for name in row["formulas"])
    metrics = {
        "herbs": {"label": "药物频次", "unit": "含该药的统计单位", "denominator": n, "multiLabel": True, "rows": _rows(herb_counts)},
        "formulas": {"label": "方剂名称提及", "unit": "含该方名的统计单位", "denominator": n, "multiLabel": True, "rows": _rows(formula_counts)},
    }
    figures = {}

    def add(key, label, note, payload, table_headers, table_rows):
        figures[key] = {"label": label, "note": note, "payload": payload,
                        "table": {"headers": table_headers, "rows": table_rows}}

    top_herbs = [herb for herb, _ in sorted(herb_counts.items(), key=lambda x: (-x[1], x[0]))[:20]]
    if len(top_herbs) >= 2:
        heat = [{"label": f"{a} / {b}", "x": a, "y": b,
                 "value": herb_counts[a] if a == b else pairs[tuple(sorted((a, b)))]}
                for a in top_herbs[:15] for b in top_herbs[:15]]
        add("case_herb_pairs_heatmap", "药对共现热图", "同一统计单位内两味药同时出现的次数；对角线是单味药频次。",
            {"chartType": "case_heatmap", "title": "高频药物共现热图", "subtitle": prefix,
             "data": heat, "axes": top_herbs[:15]}, ["药物 A", "药物 B", "共现数"],
            [[a, b, count] for (a, b), count in pairs.most_common(100)])
    rules = []
    for (a, b), count in pairs.items():
        for left, right in ((a, b), (b, a)):
            support, confidence = count / n, count / herb_counts[left]
            lift = confidence / (herb_counts[right] / n)
            if support >= .05 and confidence >= .5:
                rules.append({"antecedent": left, "consequent": right, "count": count,
                              "support": support, "confidence": confidence, "lift": lift})
    rules.sort(key=lambda r: (-r["lift"], -r["count"], r["antecedent"], r["consequent"]))
    rule_rows = [[r["antecedent"], r["consequent"], r["count"], r["support"], r["confidence"], r["lift"]] for r in rules]
    headers = ["前项", "后项", "共现数", "支持度", "置信度", "提升度"]
    if rules:
        add("case_association_network", "药物关联规则网络", "支持度 ≥ 0.05，置信度 ≥ 0.50；箭头表示规则方向，边值为共现数，图展示提升度排序前 60 条。",
            _graph([(r["antecedent"], r["consequent"], r["count"]) for r in rules], {}, "药物关联规则网络", prefix, True), headers, rule_rows[:200])
        add("case_association_bubble", "支持度—置信度气泡图", "横轴支持度、纵轴置信度；气泡大小表示共现数，颜色表示提升度。图展示提升度排序前 60 条。",
            {"chartType": "case_rules", "title": "药物关联规则分布", "subtitle": prefix,
             "data": [{"label": f"{r['antecedent']} → {r['consequent']}", "x": r["support"], "y": r["confidence"],
                       "value": r["count"], "lift": r["lift"]} for r in rules[:60]]}, headers, rule_rows[:200])
    if len(top_herbs) >= 3:
        profiles = [{"label": herb, "value": herb_counts[herb], "profile": [int(herb in herbs) for herbs in transactions]} for herb in top_herbs]
        unique_profiles = len({tuple(row["profile"]) for row in profiles})
        base = {"chartType": "case_cluster", "title": "高频药物聚类", "subtitle": f"{prefix} · 前 {len(top_herbs)} 味药 · 药物×统计单位二元矩阵", "data": profiles}
        table_rows = [[herb, herb_counts[herb]] for herb in top_herbs]
        add("case_cluster_dendrogram", "层次聚类树状图", "聚类对象是高频药物；用药物在各统计单位中的出现向量计算 Jaccard 距离，再用平均连接法合并。", {**base, "view": "dendrogram"}, ["药物", "出现频次"], table_rows)
        if unique_profiles >= 3:
            add("case_cluster_elbow", "K 值选择肘部图", "R 以固定随机种子重复运行 K-Means，展示不同 K 的簇内平方和。", {**base, "view": "elbow"}, ["药物", "出现频次"], table_rows)
        for k in (3, 4, 5):
            if k < min(len(top_herbs), unique_profiles):
                add(f"case_cluster_kmeans_{k}", f"K-Means 分组图（K={k}）", "R 在原二元特征矩阵上运行 K-Means；PCA 二维投影仅用于展示，不参与分组。", {**base, "view": "scatter", "k": k}, ["药物", "出现频次"], table_rows)

    relation_counts, types = Counter(), {}
    for row in records:
        disease = row.get("western_diagnosis")
        syndrome = row.get("syndrome")
        if disease:
            types[disease] = "disease"
        if syndrome:
            types[syndrome] = "syndrome"
        if disease and syndrome:
            relation_counts[(disease, syndrome)] += 1
        for left in [value for value in (syndrome, disease) if value]:
            for herb in row["herbs"]:
                types[herb] = "herb"
                relation_counts[(left, herb)] += 1
    if relation_counts:
        sorted_relations = [(a, b, count) for (a, b), count in relation_counts.most_common(60)]
        add("case_relations_network", "疾病—证型—药物共现图", "连接表示表格同一统计单位中的字段共现，保留登记名称；属于探索性关系，不是经核验知识图谱。",
            _graph(sorted_relations, types, "医案字段共现关系", prefix), ["起点", "终点", "共现数"], [list(row) for row in sorted_relations])
    return {"metrics": metrics, "figures": figures,
            "medicationSummary": {"prescriptionCount": prescription_count, "herbCount": len(herb_counts), "ruleCount": len(rules),
                                  "missingPrescriptionCount": n - prescription_count}}
