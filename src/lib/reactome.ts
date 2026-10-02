export type ReactomePathway = {
  stableId: string;
  name: string;
  species: string;
  matchedEntities: number;
  totalEntities: number;
  coverage: number;
  pValue: number;
  fdr: number;
};

export type ReactomeCatalogPathway = {
  stableId: string;
  name: string;
  species: "Homo sapiens";
};

type ReactomeResponse = {
  summary?: { token?: string };
  identifiersNotFound?: number;
  pathwaysFound?: number;
  pathways?: Array<{
    stId?: string;
    name?: string;
    species?: { name?: string };
    entities?: { found?: number; total?: number; ratio?: number; pValue?: number; fdr?: number };
  }>;
};

type MyGeneResponseItem = {
  query?: string;
  symbol?: string;
  name?: string;
  entrezgene?: number | string;
  notfound?: boolean;
};

export type HumanGeneMapping = {
  query: string;
  symbol: string;
  name: string | null;
  entrezGeneId: string | null;
};

const REACTOME_ANALYSIS_URL = "https://reactome.org/AnalysisService/identifiers/projection/?pageSize=100&page=1";
const REACTOME_VERSION_URL = "https://reactome.org/ContentService/data/database/version";
const REACTOME_PATHWAY_CATALOG_URL = "https://reactome.org/download/current/ReactomePathways.txt";
const MYGENE_QUERY_URL = "https://mygene.info/v3/query";

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function normalizeEnrichmentTargets(values: unknown) {
  if (!Array.isArray(values)) return [];
  return Array.from(
    new Set(
      values
        .filter((value): value is string => typeof value === "string")
        .map((value) => value.trim())
        .filter((value) => value.length > 0 && value.length <= 120)
    )
  ).slice(0, 500);
}

export async function resolveHumanGeneSymbols(targetLabels: string[]) {
  const body = new URLSearchParams({
    // MyGene treats unquoted whitespace as separate search terms.  Target labels in
    // the business database are mostly protein names, so quote every label to keep
    // each one as an exact phrase in the query-many request.
    q: targetLabels.map((label) => `"${label.replace(/"/g, "\\\"")}"`).join(","),
    scopes: "symbol,alias,name",
    fields: "symbol,name,entrezgene",
    species: "human",
    size: "1"
  });
  const response = await fetchWithTimeout(MYGENE_QUERY_URL, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
    body
  });
  if (!response.ok) {
    const details = (await response.text()).slice(0, 300);
    throw new Error(`MyGene 基因规范化服务请求失败（${response.status}）：${details || response.statusText}`);
  }

  const payload = (await response.json()) as MyGeneResponseItem[];
  const mappings = payload
    .filter((item): item is MyGeneResponseItem & { query: string; symbol: string } => Boolean(item.query && item.symbol && !item.notfound))
    .map((item) => ({
      query: item.query.trim(),
      symbol: item.symbol.trim(),
      name: item.name?.trim() || null,
      entrezGeneId: item.entrezgene == null ? null : String(item.entrezgene)
    }))
    .filter((item) => /^[A-Za-z0-9_.:-]+$/.test(item.symbol));

  const uniqueMappings = Array.from(new Map(mappings.map((item) => [item.query.toUpperCase(), item])).values());
  return {
    mappings: uniqueMappings,
    symbols: Array.from(new Set(uniqueMappings.map((item) => item.symbol))).slice(0, 500)
  };
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs = 30000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

async function fetchReactomeVersion() {
  try {
    const response = await fetchWithTimeout(REACTOME_VERSION_URL, { headers: { accept: "text/plain" } }, 10000);
    return response.ok ? (await response.text()).trim() || null : null;
  } catch {
    return null;
  }
}

export async function fetchReactomeHumanPathwayCatalog() {
  const [response, sourceVersion] = await Promise.all([
    fetchWithTimeout(REACTOME_PATHWAY_CATALOG_URL, { headers: { accept: "text/plain" } }, 60000),
    fetchReactomeVersion()
  ]);

  if (!response.ok) {
    const details = (await response.text()).slice(0, 300);
    throw new Error(`Reactome 通路目录请求失败（${response.status}）：${details || response.statusText}`);
  }

  const unique = new Map<string, ReactomeCatalogPathway>();
  for (const line of (await response.text()).split(/\r?\n/)) {
    const [stableId, name, species] = line.split("\t");
    if (!stableId?.startsWith("R-HSA-") || !name || species !== "Homo sapiens") continue;
    unique.set(stableId, { stableId, name, species });
  }

  const pathways = [...unique.values()].sort((left, right) => left.stableId.localeCompare(right.stableId));
  if (!pathways.length) throw new Error("Reactome 目录中未找到人类通路记录。");

  return { pathways, sourceVersion };
}

export async function analyzeReactomePathways(targets: string[]) {
  const response = await fetchWithTimeout(REACTOME_ANALYSIS_URL, {
    method: "POST",
    headers: { "content-type": "text/plain;charset=utf-8", accept: "application/json" },
    body: targets.join("\n")
  });
  if (!response.ok) {
    const details = (await response.text()).slice(0, 300);
    throw new Error(`Reactome 通路服务请求失败（${response.status}）：${details || response.statusText}`);
  }

  const payload = (await response.json()) as ReactomeResponse;
  const pathways = (payload.pathways ?? [])
    .map((item): ReactomePathway | null => {
      if (!item.stId || !item.name || !item.entities) return null;
      const matchedEntities = numberValue(item.entities.found);
      const totalEntities = numberValue(item.entities.total);
      const fdr = numberValue(item.entities.fdr);
      if (matchedEntities < 2 || fdr > 0.05) return null;
      return {
        stableId: item.stId,
        name: item.name,
        species: item.species?.name || "Homo sapiens",
        matchedEntities,
        totalEntities,
        coverage: numberValue(item.entities.ratio),
        pValue: numberValue(item.entities.pValue),
        fdr
      };
    })
    .filter((item): item is ReactomePathway => Boolean(item))
    .slice(0, 50);

  if (!pathways.length) {
    throw new Error("Reactome 未返回通过 FDR ≤ 0.05 且至少命中 2 个实体的通路结果。");
  }

  const sourceVersion = await fetchReactomeVersion();

  return {
    token: payload.summary?.token ?? null,
    sourceVersion,
    pathways,
    identifiersNotFound: numberValue(payload.identifiersNotFound),
    pathwaysFound: numberValue(payload.pathwaysFound)
  };
}
