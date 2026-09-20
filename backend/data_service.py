from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
import sqlite3

import pandas as pd

from .config import APP_DB, DATABASE_DIR


CACHE_DB = DATABASE_DIR.parents[3] / "tcm_pharmacology_platform" / "data_cache.db"


SOURCE_FILES = {
    "batman": {
        "file": "Batman全部数据.xlsx",
        "columns": ["中文名", "Compound Name", "Gene Name", "Score"],
        "herb": "中文名",
        "component": "Compound Name",
        "target": "Gene Name",
    },
    "herb": {
        "file": "Herb数据库全部.xlsx",
        "columns": ["Herb_cn_name", "Ingredient name", "Gene name"],
        "herb": "Herb_cn_name",
        "component": "Ingredient name",
        "target": "Gene name",
    },
    "hit": {
        "file": "HIT数据库全部.xlsx",
        "columns": ["Chinese Character", "Compound Name", "Target ID", "Symbol", "Chembl ID", "Smiles"],
        "herb": "Chinese Character",
        "component": "Compound Name",
        "target": "Symbol",
    },
    "tcmip": {
        "file": "TCMIP全部数据.xlsx",
        "columns": ["中药", "成分名称", "靶标", "相似得分", "Activity"],
        "herb": "中药",
        "component": "成分名称",
        "target": "靶标",
    },
    "tcmsp": {
        "file": "tcmsp全部数据.xlsx",
        "columns": ["中药", "成分", "靶点基因"],
        "herb": "中药",
        "component": "成分",
        "target": "靶点基因",
    },
}


def _clean(value: object) -> str:
    return str(value).strip() if pd.notna(value) else ""


def _split_targets(value: object) -> list[str]:
    text = _clean(value)
    if not text:
        return []
    return [item.strip() for item in re.split(r"[;,，；/|]", text) if item.strip()]


def _contains(series: pd.Series, q: str) -> pd.Series:
    return series.astype(str).str.contains(re.escape(q), case=False, na=False)


@lru_cache(maxsize=16)
def load_source(name: str) -> pd.DataFrame:
    meta = SOURCE_FILES[name]
    path = DATABASE_DIR / meta["file"]
    return pd.read_excel(path, usecols=meta["columns"])


@lru_cache(maxsize=2)
def load_disease_herb() -> pd.DataFrame:
    return pd.read_excel(DATABASE_DIR / "疾病_中药.xlsx", usecols=["疾病", "中药", "靶点基因"])


@lru_cache(maxsize=2)
def load_disease_targets() -> pd.DataFrame:
    return pd.read_excel(DATABASE_DIR / "combined_results.xlsx", usecols=["靶点基因", "疾病", "来源文件"])


def sources() -> list[dict]:
    result = []
    for key, meta in SOURCE_FILES.items():
        path = DATABASE_DIR / meta["file"]
        result.append({
            "key": key,
            "name": meta["file"],
            "exists": path.exists(),
            "size_mb": round(path.stat().st_size / 1024 / 1024, 2) if path.exists() else 0,
            "fields": meta["columns"],
        })
    for filename in ["疾病_中药.xlsx", "combined_results.xlsx"]:
        path = DATABASE_DIR / filename
        result.append({
            "key": Path(filename).stem,
            "name": filename,
            "exists": path.exists(),
            "size_mb": round(path.stat().st_size / 1024 / 1024, 2) if path.exists() else 0,
            "fields": [],
        })
    return result


def health() -> dict:
    users = 0
    if APP_DB.exists():
        with sqlite3.connect(APP_DB) as con:
            users = con.execute("select count(*) from users").fetchone()[0]
    return {
        "status": "ok",
        "database_dir": str(DATABASE_DIR),
        "cache_db": str(CACHE_DB),
        "cache_ready": CACHE_DB.exists(),
        "source_count": len(sources()),
        "user_count": users,
    }


def _cache() -> sqlite3.Connection | None:
    if not CACHE_DB.exists():
        return None
    con = sqlite3.connect(CACHE_DB)
    con.row_factory = sqlite3.Row
    return con


def _like(q: str) -> str:
    return f"%{q.strip()}%"


def search_disease(q: str, limit: int = 100) -> dict:
    q = q.strip()
    if not q:
        return {"query": q, "herbs": [], "targets": [], "links": []}
    con = _cache()
    if con:
        with con:
            herbs = [r["herb"] for r in con.execute("select distinct herb from disease_herb_target where disease like ? and herb <> '' order by herb limit ?", (_like(q), limit))]
            targets_a = [r["target"] for r in con.execute("select distinct target from disease_herb_target where disease like ? and target <> '' order by target limit ?", (_like(q), limit))]
            targets_b = [r["target"] for r in con.execute("select distinct target from disease_target where disease like ? and target <> '' order by target limit ?", (_like(q), limit))]
            rows = [dict(r) for r in con.execute("select disease as 疾病, herb as 中药, target as 靶点基因 from disease_herb_target where disease like ? limit ?", (_like(q), limit))]
        targets = sorted(set(targets_a + targets_b))[:limit]
        return {"query": q, "herbs": herbs, "targets": targets, "links": rows, "counts": {"herbs": len(herbs), "targets": len(targets), "links": len(rows)}}

    dh = load_disease_herb()
    dt = load_disease_targets()
    dhm = dh[_contains(dh["疾病"], q)]
    dtm = dt[_contains(dt["疾病"], q)]

    herbs = sorted({_clean(v) for v in dhm["中药"].dropna() if _clean(v)})[:limit]
    targets = sorted({_clean(v) for v in pd.concat([dhm["靶点基因"].dropna(), dtm["靶点基因"].dropna()]) if _clean(v)})[:limit]
    links = dhm[["疾病", "中药", "靶点基因"]].drop_duplicates().head(limit).to_dict("records")
    return {"query": q, "herbs": herbs, "targets": targets, "links": links, "counts": {"herbs": len(herbs), "targets": len(targets), "links": len(links)}}


def search_herb(q: str, limit: int = 200) -> dict:
    q = q.strip()
    components: dict[str, set[str]] = {}
    rows = []
    if not q:
        return {"query": q, "components": [], "targets": [], "links": []}
    con = _cache()
    if con:
        with con:
            rows = [dict(r) for r in con.execute("select source, herb, component, target from herb_component_target where herb like ? limit ?", (_like(q), limit))]
            components_list = [r["component"] for r in con.execute("select distinct component from herb_component_target where herb like ? and component <> '' order by component limit ?", (_like(q), limit))]
            targets_list = [r["target"] for r in con.execute("select distinct target from herb_component_target where herb like ? and target <> '' order by target limit ?", (_like(q), limit))]
        links = [{"source": r["source"], "herb": r["herb"], "component": r["component"], "targets": _split_targets(r["target"])} for r in rows]
        return {"query": q, "components": components_list, "targets": targets_list, "links": links, "counts": {"components": len(components_list), "targets": len(targets_list), "links": len(links)}}

    for source, meta in SOURCE_FILES.items():
        df = load_source(source)
        matched = df[_contains(df[meta["herb"]], q)]
        for _, row in matched.head(limit).iterrows():
            comp = _clean(row.get(meta["component"]))
            if not comp:
                continue
            target_values = _split_targets(row.get(meta["target"]))
            components.setdefault(comp, set()).update(target_values)
            rows.append({"source": source, "herb": _clean(row.get(meta["herb"])), "component": comp, "targets": target_values[:20]})

    targets = sorted({t for values in components.values() for t in values})
    return {
        "query": q,
        "components": sorted(components.keys())[:limit],
        "targets": targets[:limit],
        "links": rows[:limit],
        "counts": {"components": len(components), "targets": len(targets), "links": len(rows)},
    }


def search_component(q: str, limit: int = 200) -> dict:
    q = q.strip()
    rows = []
    targets: set[str] = set()
    if not q:
        return {"query": q, "targets": [], "links": []}
    con = _cache()
    if con:
        with con:
            rows = [dict(r) for r in con.execute("select source, herb, component, target from herb_component_target where component like ? limit ?", (_like(q), limit))]
            targets_list = [r["target"] for r in con.execute("select distinct target from herb_component_target where component like ? and target <> '' order by target limit ?", (_like(q), limit))]
        links = [{"source": r["source"], "herb": r["herb"], "component": r["component"], "targets": _split_targets(r["target"])} for r in rows]
        return {"query": q, "targets": targets_list, "links": links, "counts": {"targets": len(targets_list), "links": len(links)}}

    for source, meta in SOURCE_FILES.items():
        df = load_source(source)
        matched = df[_contains(df[meta["component"]], q)]
        for _, row in matched.head(limit).iterrows():
            target_values = _split_targets(row.get(meta["target"]))
            targets.update(target_values)
            rows.append({
                "source": source,
                "herb": _clean(row.get(meta["herb"])),
                "component": _clean(row.get(meta["component"])),
                "targets": target_values[:20],
            })
    return {"query": q, "targets": sorted(targets)[:limit], "links": rows[:limit], "counts": {"targets": len(targets), "links": len(rows)}}


def intersect_targets(left: list[str], right: list[str]) -> dict:
    a = {_clean(v).upper() for v in left if _clean(v)}
    b = {_clean(v).upper() for v in right if _clean(v)}
    common = sorted(a & b)
    return {"left_count": len(a), "right_count": len(b), "intersection_count": len(common), "intersection": common}


def compare_components(detected: list[str], reference: list[str]) -> dict:
    d = {_clean(v).lower() for v in detected if _clean(v)}
    r = {_clean(v).lower() for v in reference if _clean(v)}
    matched = sorted(d & r)
    missing = sorted(d - r)
    extra = sorted(r - d)
    ratio = round(len(matched) / len(d) * 100, 2) if d else 0
    return {"detected_count": len(d), "reference_count": len(r), "matched_count": len(matched), "match_rate": ratio, "matched": matched, "unmatched_detected": missing, "reference_only": extra[:500]}


def _parse_formula(formula: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，、;；\n]+", formula) if item.strip()]


def scientist_hypothesis(question: str, disease: str, formula: str, focus: str) -> dict:
    herbs = _parse_formula(formula)
    disease_result = search_disease(disease, limit=80)
    herb_results = [search_herb(herb, limit=80) for herb in herbs]
    herb_targets = sorted({
        target
        for result in herb_results
        for target in result.get("targets", [])
        if _clean(target)
    })
    disease_targets = disease_result.get("targets", [])
    intersection = intersect_targets(disease_targets, herb_targets)["intersection"]
    components = []
    for result in herb_results:
        components.extend(result.get("components", [])[:20])
    components = sorted(set(components))[:60]
    top_targets = intersection[:12] if intersection else herb_targets[:12]

    title = f"基于中医药理知识图谱的{formula.replace(',', '、')}干预{disease}潜在机制研究"
    abstract = (
        f"本研究面向{focus}，以“{question}”为核心问题，整合疾病靶点、中药成分-靶点关系、"
        "ChEMBL 分子活性数据与后续文献证据，构建从方剂组成到候选靶点的证据链。"
        f"初步数据检索获得疾病相关靶点 {len(disease_targets)} 个、方剂相关靶点 {len(herb_targets)} 个，"
        f"共同候选靶点 {len(intersection)} 个。研究拟通过网络药理学富集、细胞模型和基因表达验证评估候选机制。"
    )
    rationale = [
        f"疾病侧：{disease} 检索得到 {len(disease_result.get('herbs', []))} 个相关中药线索和 {len(disease_targets)} 个疾病靶点。",
        f"方剂侧：{formula} 共检索到 {len(components)} 个代表性成分和 {len(herb_targets)} 个成分关联靶点。",
        f"机制侧：疾病靶点与方剂靶点交集为 {len(intersection)} 个，优先关注 {', '.join(top_targets[:6]) if top_targets else '待补充靶点'}。",
        "可验证性：共同靶点可通过转录组差异表达、qPCR、Western blot 或通路富集进行验证。",
    ]
    methods = [
        "使用疾病靶点库与中药成分-靶点库构建二部关系网络。",
        "对方剂中各味中药分别检索成分与靶点，合并去重后计算疾病-方剂共同靶点。",
        "结合 ChEMBL 查询关键成分的 SMILES、活性类型、pChEMBL 值和靶标证据。",
        "对共同靶点进行 GO/KEGG 富集，筛选炎症、纤维化、免疫调控相关通路。",
        "设计体外模型验证核心靶点表达变化，并与空白组、模型组、阳性药组进行比较。",
    ]
    experiments = {
        "baselines": ["单数据库检索", "无 ChEMBL 活性补强的网络药理学流程", "人工经验筛选靶点"],
        "metrics": ["共同靶点数量", "文献证据强度", "富集通路显著性", "实验表达差异", "假设可解释性评分"],
        "validation": ["细胞模型", "转录组或公开 GEO 数据复核", "qPCR/Western blot", "分子对接或活性数据佐证"],
    }
    references = [
        "BATMAN-TCM: Bioinformatics Analysis Tool for Molecular mechANism of Traditional Chinese Medicine.",
        "HERB: A high-throughput experiment- and reference-guided database of traditional Chinese medicine.",
        "HIT 2.0: Herbal Ingredients' Targets Database.",
        "TCMSP: Traditional Chinese Medicine Systems Pharmacology Database and Analysis Platform.",
        "ChEMBL 36 local SQLite database.",
    ]
    return {
        "input": {"question": question, "disease": disease, "formula": herbs, "focus": focus},
        "problem_statement": f"当前对{formula}干预{disease}的多成分、多靶点协同机制仍缺少可复核的数据链路和实验验证路径。",
        "paper_title": title,
        "paper_abstract": abstract,
        "rationale": rationale,
        "technical_details": ["Qwen/千问多智能体推理", "RAG 证据检索", "中医药理知识图谱", "ChEMBL 活性数据补强", "网络药理学与富集分析", "体外实验验证"],
        "datasets": {
            "source": ["BATMAN-TCM", "HERB", "HIT", "TCMIP", "TCMSP", "ChEMBL 36", "待接入真实文献库"],
            "target": ["疾病模型表达数据", "方剂干预后转录组数据", "关键靶点蛋白表达数据", "候选成分活性验证数据"],
        },
        "methods": methods,
        "experiments": experiments,
        "results": {
            "disease_target_count": len(disease_targets),
            "formula_target_count": len(herb_targets),
            "intersection_count": len(intersection),
            "top_intersection_targets": intersection[:30],
            "representative_components": components[:30],
        },
        "references": references,
        "evidence": {
            "disease_herbs": disease_result.get("herbs", [])[:20],
            "disease_targets": disease_targets[:30],
            "herb_summaries": [
                {
                    "herb": herbs[i] if i < len(herbs) else f"herb_{i+1}",
                    "component_count": result.get("counts", {}).get("components", 0),
                    "target_count": result.get("counts", {}).get("targets", 0),
                    "components": result.get("components", [])[:12],
                    "targets": result.get("targets", [])[:12],
                }
                for i, result in enumerate(herb_results)
            ],
        },
        "qwen_integration": "当前为规则化证据整合与报告生成原型；接入阿里云百炼 Qwen 后，可由多智能体完成文献检索、批判性评审和多轮迭代。",
    }
