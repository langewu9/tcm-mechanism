export const R_CHARTS = [
  ["ppi_network", "PPI 网络图"], ["ppi_degree", "PPI 连接度排行"],
  ["evidence_network", "中药—成分—靶点—疾病网络"], ["gene_pathway_network", "基因—通路网络"],
  ["gene_pathway_distribution", "通路关联基因分布"], ["proteomics_go_kegg_bar", "GO / KEGG 富集显著性点图"],
  ["proteomics_go_kegg_enrichment", "GO / KEGG 富集气泡图"], ["reactome_enrichment", "Reactome 通路气泡图"],
  ["proteomics_summary", "蛋白组学分析概览"], ["proteomics_top_nodes", "本地通路网络连接度"],
  ["overlap", "中药—疾病靶点交集"], ["components", "关联成分靶点数"],
  ["pathways", "关联通路靶点数"], ["proteomics_volcano", "差异蛋白火山图"],
  ["catalog_summary", "检索实体与证据概览"], ["catalog_degree", "检索实体连接度"],
] as const;
