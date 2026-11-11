"""Frozen pure reference functions for parity tests.

Source: backend/data_service.py at 078d374852d82ad398e98ff8e97d11f7eb2e3a62.
Full original file SHA-256: 7fae7384a64b236d787696fbe1288c583d680df59054e8592cd93f60897aa6f9.
Only these definitions are executed with synthetic local collaborators.
"""

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
