export const DEMO_WARNING = "合成演示 · 非真实实验/医案 · 不代表数据库证据、模型推理或临床结论";
export const R_CHARTS = [
  ["ppi_network", "PPI 网络图"], ["ppi_degree", "PPI 连接度排行"],
  ["evidence_network", "中药—成分—靶点—疾病网络"], ["gene_pathway_network", "基因—通路网络"],
  ["gene_pathway_distribution", "通路关联基因分布"], ["proteomics_go_kegg_bar", "GO / KEGG 富集条形图"],
  ["proteomics_go_kegg_enrichment", "GO / KEGG 富集气泡图"], ["reactome_enrichment", "Reactome 通路气泡图"],
  ["proteomics_summary", "蛋白组学分析概览"], ["proteomics_top_nodes", "本地通路网络连接度"],
  ["overlap", "中药—疾病靶点交集"], ["components", "关联成分靶点数"],
  ["pathways", "关联通路靶点数"], ["proteomics_volcano", "差异蛋白火山图"],
] as const;
export const demoEntities = [
  { id: "DEMO:H1", label: "演示中药甲", type: "herb" }, { id: "DEMO:C1", label: "演示成分甲", type: "compound" },
  { id: "DEMO:G1", label: "DEMO_GENE_01", type: "target" }, { id: "DEMO:G2", label: "DEMO_GENE_02", type: "target" },
  { id: "DEMO:P1", label: "演示通路甲", type: "pathway" }, { id: "DEMO:D1", label: "演示疾病甲", type: "disease" },
];
export const demoRelations = [
  ["DEMO:H1", "DEMO:C1", "contains"], ["DEMO:C1", "DEMO:G1", "associated_with"],
  ["DEMO:C1", "DEMO:G2", "associated_with"], ["DEMO:G1", "DEMO:P1", "participates_in"], ["DEMO:D1", "DEMO:G1", "associated_with"],
].map(([source, target, relation], index) => ({ source, target, relation, sourceRecordId: `DEMO-REL-${index+1}`, sourceSlug: "synthetic-demo-only" }));
export const demoNetwork = { nodes: demoEntities, links: demoRelations };
export const demoProteinRows = Array.from({ length: 20 }, (_, index) => ({
  label: `DEMO_PROTEIN_${String(index+1).padStart(2, "0")}`, log2FoldChange: (index % 2 ? -1 : 1) * (0.2 + index / 10),
  pValue: index % 4 === 0 ? 0.2 : 0.001 * (index + 1), fdr: index % 4 === 0 ? 0.4 : 0.002 * (index + 1),
}));
export const demoCase = {
  title: "合成教学医案（虚构）", text: "虚构研究个体，反复咳嗽，口干，舌红，脉细。仅用于界面展示，未进行诊断。",
  observations: ["咳嗽", "口干", "舌红", "脉细"], candidates: ["演示证候甲", "演示方剂甲"],
  source: "SYNTHETIC_CASE_NOT_A_PATIENT", warning: "候选是界面样例，不是诊断或处方。",
};
export const demoModules = [
  { key: "overview", label: "研究总览", route: "/dashboard", stages: ["查看资产", "查看任务", "进入研究模块"], gap: "真实目录与资产数量以工作区统计为准；演示统计独立展示。", input: { datasets: 1, cases: 1, entities: 6, relations: 5 } },
  { key: "research", label: "药理检索", route: "/research", stages: ["选择查询", "筛选记录", "核查来源"], gap: "本地数据需正式导入；ChEMBL 等外部检索需逐次同意。", input: { query: "演示", entities: demoEntities, relations: demoRelations, source: "SYNTHETIC_NOT_DATABASE" } },
  { key: "datasets", label: "数据资产", route: "/datasets", stages: ["选择合成数据", "检查字段", "下载演示 key"], gap: "工作区支持上传、私有下载及保留原文件的归档/恢复；生产存储与备份仍需验收。演示不入库。", input: { filename: "synthetic-proteomics-demo.json", columns: ["label", "log2FoldChange", "pValue", "fdr"], rows: demoProteinRows } },
  { key: "proteomics", label: "蛋白组学", route: "/proteomics", stages: ["检查输入", "本地阈值筛选", "查看 R 图表"], gap: "本地映射依赖知识库；真实富集/PPI 需有结果；PCA/热图/GSEA 仍待实现。", input: { log2FcMin: 1, fdrMax: 0.05, rows: demoProteinRows } },
  { key: "network", label: "网络药理与图谱", route: "/visualization", stages: ["中药侧/疾病侧", "计算交集", "核查关系"], gap: "演示关系全部虚构，不冒充 STRING 或数据库查询。", input: { herbTargets: ["DEMO:G1", "DEMO:G2"], diseaseTargets: ["DEMO:G1", "DEMO:G3"], network: demoNetwork } },
  { key: "cases", label: "医案分析", route: "/cases", stages: ["脱敏教学文本", "观察与候选", "人工审核演示"], gap: "真实医案需授权脱敏；候选需可用模型服务及研究者确认。", input: demoCase },
  { key: "analysis", label: "证候—方药分析", route: "/analysis", stages: ["教学研究问题", "规则示例", "证据边界"], gap: "真实证候方药链路依赖目录，不能作为诊断系统。", input: { query: "虚构医案中的咳嗽和口干如何展示证据链？", case: demoCase, network: demoNetwork } },
  { key: "assistant", label: "科研助手", route: "/assistant", stages: ["选择演示证据", "输入演示问题", "模板回答与引用"], gap: "模型按原要求保持不动；本次是模板展示，不是推理。", input: { question: "演示中药甲有哪些关联靶点？", evidenceIds: ["DEMO-REL-1", "DEMO-REL-2"], modelInvoked: false } },
  { key: "sources", label: "动态更新与主键统一", route: "/admin/sources", stages: ["预览版本差异", "复核歧义映射", "演示确认应用"], gap: "真实同步需合法数据源、人工确认与备份；定时预览当前未启用。", input: { source: "DEMO_PROVIDER", version: "DEMO-V2", mappings: [{ canonicalId: "DEMO:G1", sourceId: "DEMO_A:001", status: "reviewed" }, { canonicalId: null, sourceId: "DEMO_B:002", status: "ambiguous" }], diff: { added: 2, changed: 1, ambiguous: 1 } } },
  { key: "accounts", label: "账号与系统管理", route: "/admin", stages: ["模拟角色", "查看权限说明", "回到真实登录"], gap: "角色演示不授予权限；生产注册邮件、账号隔离及管理员权限需验收。", input: { roles: ["研究者", "管理员"], authenticationBypassed: false, credentialsIncluded: false } },
] as const;
export type DemoModuleKey = (typeof demoModules)[number]["key"];
export function moduleForPath(path: string) {
  if (path === "/network-pharmacology") return demoModules.find(module => module.key === "network");
  return demoModules.find(module => module.route === path);
}
export function evaluateDemo(key: DemoModuleKey, query = "演示", fc = 1, fdr = 0.05) {
  if (key === "research") return { matches: demoEntities.filter(entity => entity.label.toLowerCase().includes(query.toLowerCase())), source: "SYNTHETIC_NOT_DATABASE" };
  if (key === "proteomics") return { rows: demoProteinRows.map(row => ({ ...row, selected: Math.abs(row.log2FoldChange) >= fc && row.fdr <= fdr })), thresholds: { fc, fdr }, algorithm: "local-demo-filter-not-inference" };
  if (key === "network") return { strictIntersection: ["DEMO:G1"], herbOnly: ["DEMO:G2"], diseaseOnly: ["DEMO:G3"], network: demoNetwork };
  if (key === "assistant") return { answer: "合成模板：DEMO-REL-2 连接演示成分甲与 DEMO_GENE_01。只用于展示引用格式，不是模型推理或真实数据库证据。", citations: ["DEMO-REL-2"], modelInvoked: false };
  return demoModules.find(module => module.key === key)?.input;
}
