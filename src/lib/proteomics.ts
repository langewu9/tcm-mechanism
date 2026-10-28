export type ProteomicsColumnMapping = {
  geneColumn: string;
  proteinColumn: string;
  log2FcColumn: string;
  pValueColumn: string;
  fdrColumn: string;
  directionColumn: string;
};

export type ProteomicsThresholds = {
  log2FcMin: number;
  fdrMax: number;
  pValueMax: number;
};

export type ParsedProteomicsRow = {
  index: number;
  originalLabel: string;
  proteinName: string | null;
  log2FoldChange: number | null;
  pValue: number | null;
  fdr: number | null;
  direction: string | null;
  raw: Record<string, string>;
};

export type LocalGeneRecord = {
  symbol: string;
  name: string | null;
  externalId: string | null;
};

export type LocalTargetRecord = {
  symbol: string;
  pathways: Array<{ name: string; externalId: string | null }>;
};

export type ProteomicsNetwork = {
  nodes: Array<{ id: string; label: string; type: string }>;
  links: Array<{ source: string; target: string; relation: string }>;
};

const aliases = {
  geneColumn: ["gene", "gene_symbol", "gene symbol", "symbol", "genes", "基因", "基因名", "基因符号", "靶点", "靶点基因"],
  proteinColumn: ["protein", "protein_name", "protein name", "uniprot", "蛋白", "蛋白质", "蛋白名称", "蛋白名"],
  log2FcColumn: ["log2fc", "log2_fc", "log2 fold change", "log2foldchange", "logfc", "fc", "log2倍数变化", "差异倍数"],
  pValueColumn: ["pvalue", "p_value", "p value", "p-value", "p值", "p 值"],
  fdrColumn: ["fdr", "adj.p.val", "adj_p_val", "padj", "adjusted p value", "qvalue", "q-value", "校正p值", "校正 p 值"],
  directionColumn: ["direction", "regulation", "change", "trend", "变化方向", "上调下调"]
} satisfies Record<keyof ProteomicsColumnMapping, string[]>;

function normalizeColumn(value: string) {
  return value.trim().toLowerCase().replace(/[\s_\-.()（）]+/g, "");
}

function canonicalLabel(value: string) {
  return value.trim().replace(/^"|"$/g, "").toUpperCase();
}

function clean(value: unknown) {
  return value == null ? "" : String(value).trim();
}

function parseNumber(value: unknown) {
  const text = clean(value).replace(/,/g, "");
  if (!text || /^(na|nan|null|none|-)$/i.test(text)) return null;
  const isPercent = text.endsWith("%");
  const parsed = Number(text.replace(/%$/, ""));
  if (!Number.isFinite(parsed)) return null;
  return isPercent ? parsed / 100 : parsed;
}

function findColumn(columns: string[], requested: string, field: keyof ProteomicsColumnMapping) {
  const normalized = new Map(columns.map((column) => [normalizeColumn(column), column]));
  const candidate = requested.trim();
  if (candidate) {
    const exact = normalized.get(normalizeColumn(candidate));
    if (exact) return exact;
    throw new Error(`找不到字段“${candidate}”，当前文件字段为：${columns.join("、")}`);
  }
  return aliases[field]
    .map((item) => normalized.get(normalizeColumn(item)))
    .find((item): item is string => Boolean(item)) || "";
}

export function resolveProteomicsMapping(columns: string[], requested: Partial<ProteomicsColumnMapping>): ProteomicsColumnMapping {
  const geneColumn = findColumn(columns, requested.geneColumn || "", "geneColumn");
  const proteinColumn = findColumn(columns, requested.proteinColumn || "", "proteinColumn");
  if (!geneColumn && !proteinColumn) throw new Error(`未识别到基因或蛋白字段，请填写列名。当前字段为：${columns.join("、")}`);
  return {
    geneColumn,
    proteinColumn,
    log2FcColumn: findColumn(columns, requested.log2FcColumn || "", "log2FcColumn"),
    pValueColumn: findColumn(columns, requested.pValueColumn || "", "pValueColumn"),
    fdrColumn: findColumn(columns, requested.fdrColumn || "", "fdrColumn"),
    directionColumn: findColumn(columns, requested.directionColumn || "", "directionColumn")
  };
}

export function parseProteomicsRows(rows: Record<string, string>[], mapping: ProteomicsColumnMapping, thresholds: ProteomicsThresholds) {
  const parsedRows: ParsedProteomicsRow[] = rows.map((raw, index) => {
    const gene = clean(mapping.geneColumn ? raw[mapping.geneColumn] : "");
    const protein = clean(mapping.proteinColumn ? raw[mapping.proteinColumn] : "");
    const originalLabel = gene || protein;
    const log2FoldChange = parseNumber(mapping.log2FcColumn ? raw[mapping.log2FcColumn] : "");
    const pValue = parseNumber(mapping.pValueColumn ? raw[mapping.pValueColumn] : "");
    const fdr = parseNumber(mapping.fdrColumn ? raw[mapping.fdrColumn] : "");
    const rawDirection = clean(mapping.directionColumn ? raw[mapping.directionColumn] : "");
    const direction = rawDirection || (log2FoldChange == null ? null : log2FoldChange >= 0 ? "上调" : "下调");
    return {
      index,
      originalLabel,
      proteinName: protein || null,
      log2FoldChange,
      pValue,
      fdr,
      direction: direction || null,
      raw
    };
  }).filter((row) => Boolean(row.originalLabel));

  const selectedRows = parsedRows.filter((row) => {
    const passesFc = row.log2FoldChange == null || Math.abs(row.log2FoldChange) >= thresholds.log2FcMin;
    const passesSignificance = row.fdr != null
      ? row.fdr <= thresholds.fdrMax
      : row.pValue == null || row.pValue <= thresholds.pValueMax;
    return passesFc && passesSignificance;
  });
  return { parsedRows, selectedRows };
}

function looksLikeGeneSymbol(value: string) {
  return /^[A-Za-z][A-Za-z0-9_.:-]{1,31}$/.test(value);
}

export function buildProteomicsResult(options: {
  selectedRows: ParsedProteomicsRow[];
  referenceTargets: string[];
  geneRecords: LocalGeneRecord[];
  targetRecords: LocalTargetRecord[];
}) {
  const geneByLabel = new Map<string, LocalGeneRecord>();
  options.geneRecords.forEach((gene) => {
    geneByLabel.set(canonicalLabel(gene.symbol), gene);
    if (gene.name) geneByLabel.set(canonicalLabel(gene.name), gene);
  });
  const targetBySymbol = new Map(options.targetRecords.map((target) => [canonicalLabel(target.symbol), target]));
  const labels = Array.from(new Set(options.selectedRows.map((row) => row.originalLabel))).slice(0, 5000);
  const mappingByLabel = new Map<string, LocalGeneRecord>();
  const unmapped: string[] = [];
  labels.forEach((label) => {
    const local = geneByLabel.get(canonicalLabel(label)) || targetBySymbol.get(canonicalLabel(label));
    if (local) mappingByLabel.set(canonicalLabel(label), { symbol: local.symbol, name: "name" in local ? local.name : null, externalId: null });
    else if (looksLikeGeneSymbol(label)) mappingByLabel.set(canonicalLabel(label), { symbol: label.toUpperCase(), name: null, externalId: null });
    else unmapped.push(label);
  });
  const mappedSymbols = Array.from(new Set([...mappingByLabel.values()].map((mapping) => mapping.symbol)));
  const referenceSet = new Set(options.referenceTargets.map((item) => canonicalLabel(item)).filter(Boolean));
  const overlap = mappedSymbols.filter((symbol) => referenceSet.has(canonicalLabel(symbol)));
  const proteomicsOnly = mappedSymbols.filter((symbol) => !referenceSet.has(canonicalLabel(symbol)));
  const referenceOnly = Array.from(referenceSet).filter((symbol) => !mappedSymbols.some((item) => canonicalLabel(item) === symbol));

  const networkNodes = new Map<string, { id: string; label: string; type: string }>();
  const networkLinks: Array<{ source: string; target: string; relation: string }> = [];
  mappedSymbols.forEach((symbol) => networkNodes.set(`target:${symbol}`, { id: `target:${symbol}`, label: symbol, type: "target" }));
  mappedSymbols.forEach((symbol) => {
    const target = targetBySymbol.get(canonicalLabel(symbol));
    target?.pathways.forEach((pathway) => {
      const pathwayId = pathway.externalId || pathway.name;
      const pathwayNodeId = `pathway:${pathwayId}`;
      networkNodes.set(pathwayNodeId, { id: pathwayNodeId, label: pathway.name, type: "pathway" });
      networkLinks.push({ source: `target:${symbol}`, target: pathwayNodeId, relation: "差异蛋白-通路" });
    });
  });

  const degree = new Map<string, number>();
  networkLinks.forEach((link) => {
    degree.set(link.source, (degree.get(link.source) || 0) + 1);
    degree.set(link.target, (degree.get(link.target) || 0) + 1);
  });
  const topNodes = mappedSymbols.map((symbol) => {
    const rows = options.selectedRows.filter((row) => mappingByLabel.get(canonicalLabel(row.originalLabel))?.symbol === symbol);
    const representative = [...rows].sort((left, right) => Math.abs(right.log2FoldChange || 0) - Math.abs(left.log2FoldChange || 0))[0];
    const target = targetBySymbol.get(canonicalLabel(symbol));
    return {
      symbol,
      degree: degree.get(`target:${symbol}`) || 0,
      log2FoldChange: representative?.log2FoldChange ?? null,
      fdr: representative?.fdr ?? null,
      direction: representative?.direction ?? null,
      pathways: target?.pathways.map((pathway) => pathway.name) || []
    };
  }).sort((left, right) => right.degree - left.degree || Math.abs(right.log2FoldChange || 0) - Math.abs(left.log2FoldChange || 0)).slice(0, 30);

  const rowResults = options.selectedRows.map((row) => {
    const mapping = mappingByLabel.get(canonicalLabel(row.originalLabel));
    return { ...row, symbol: mapping?.symbol || null, geneName: mapping?.name || null };
  });
  const localAnnotatedCount = mappedSymbols.filter((symbol) => targetBySymbol.has(canonicalLabel(symbol))).length;
  return {
    summary: {
      selectedRowCount: options.selectedRows.length,
      uniqueLabelCount: labels.length,
      normalizedCount: mappedSymbols.length,
      unmappedCount: unmapped.length,
      localAnnotatedCount,
      referenceCount: referenceSet.size,
      candidateOverlapCount: overlap.length,
      pathwayCount: new Set(networkLinks.map((link) => link.target)).size,
      enrichmentMode: "LOCAL",
      enrichmentNote: "当前仅使用本地 Gene、Target、Pathway 关联；未向外部服务发送上传数据。"
    },
    rows: rowResults,
    unmapped,
    topNodes,
    pathways: Array.from(new Map(
      networkLinks.map((link) => {
        const target = networkNodes.get(link.target)!;
        return [target.id, { name: target.label, stableId: target.id.replace(/^pathway:/, "") }];
      })
    ).values()),
    validation: { referenceTargets: Array.from(referenceSet), overlap, proteomicsOnly, referenceOnly },
    network: { nodes: Array.from(networkNodes.values()), links: networkLinks } satisfies ProteomicsNetwork
  };
}
