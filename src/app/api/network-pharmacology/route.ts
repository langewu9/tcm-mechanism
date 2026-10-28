import { existsSync } from "node:fs";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { NextResponse } from "next/server";
import { handleRouteError, jsonError, requireApiUser } from "@/lib/api";
import { resolveDiseaseQueries, type DiseaseResolution } from "@/lib/disease-query";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";

type CacheRow = Record<string, unknown>;

type TargetEvidence = {
  label: string;
  rows: CacheRow[];
  components: Set<string>;
  herbs: Set<string>;
  sources: Set<string>;
  diseases: Set<string>;
};

function clean(value: unknown) {
  return value == null ? "" : String(value).trim();
}

function normalizeTarget(value: unknown) {
  return clean(value).toUpperCase().replace(/\s+/g, " ");
}

function splitTargets(value: unknown) {
  return clean(value)
    .split(/[;,，；/|]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function boundedLimit(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 12000;
  return Math.min(Math.max(Math.trunc(parsed), 500), 30000);
}

function parseHerbs(value: unknown) {
  return Array.from(
    new Set(
      clean(value)
        .split(/[,，、;；|/\n\r]+/)
        .map((item) => item.trim())
        .filter(Boolean)
    )
  ).slice(0, 12);
}

function isHeaderLike(value: string) {
  return ["靶点基因", "GENE NAME", "TARGET", "TARGET ID", "SYMBOL"].includes(normalizeTarget(value));
}

function addEvidence(map: Map<string, TargetEvidence>, target: string, row: CacheRow, options: Partial<Record<"component" | "herb" | "source" | "disease", string>>) {
  const normalized = normalizeTarget(target);
  if (!normalized || isHeaderLike(target)) return;
  const evidence = map.get(normalized) ?? {
    label: clean(target),
    rows: [],
    components: new Set<string>(),
    herbs: new Set<string>(),
    sources: new Set<string>(),
    diseases: new Set<string>()
  };
  evidence.rows.push(row);
  if (options.component) evidence.components.add(options.component);
  if (options.herb) evidence.herbs.add(options.herb);
  if (options.source) evidence.sources.add(options.source);
  if (options.disease) evidence.diseases.add(options.disease);
  map.set(normalized, evidence);
}

function preview(values: Iterable<string>, size = 10) {
  return Array.from(values).filter(Boolean).slice(0, size);
}

function asRows(statementRows: unknown[]) {
  return statementRows.map((row) => ({ ...(row as CacheRow) }));
}

function uniqueRows(rows: CacheRow[], keys: string[]) {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const signature = keys.map((key) => clean(row[key])).join("\u001f");
    if (seen.has(signature)) return false;
    seen.add(signature);
    return true;
  });
}

export async function POST(request: Request) {
  try {
    await requireApiUser();
    const body = await request.json();
    const herbs = parseHerbs(body.herb ?? body.herbs);
    const herb = herbs.join("、");
    const disease = clean(body.disease);
    const limit = boundedLimit(body.limit);
    if (!herbs.length || !disease) return jsonError("请输入中药名称和疾病名称");

    const cachePath = join(process.cwd(), "data_cache.db");
    if (!existsSync(cachePath)) {
      return jsonError("本地 data_cache.db 未找到，请先完成数据库缓存构建或运行 FastAPI 数据准备流程", 500);
    }

    const db = new DatabaseSync(cachePath, { readOnly: true });
    let herbRows: CacheRow[] = [];
    let diseaseTargetRows: CacheRow[] = [];
    let diseaseHerbRows: CacheRow[] = [];
    let directRows: CacheRow[] = [];
    let diseaseResolution: DiseaseResolution = { original: disease, queries: [disease], matchedNames: [] };

    try {
      const herbStatement = db.prepare(
        "select source, herb, component, target from herb_component_target where herb like ? and herb <> '' and target <> '' limit ?"
      );
      for (const item of herbs) {
        herbRows.push(...asRows(herbStatement.all(`%${item}%`, limit)));
      }
      herbRows = uniqueRows(herbRows, ["source", "herb", "component", "target"]).slice(0, limit);

      const availableDiseases = asRows(
        db.prepare(
          "select distinct disease from disease_target where disease <> '' union select distinct disease from disease_herb_target where disease <> ''"
        ).all()
      ).map((row) => clean(row.disease)).filter((name) => name && name !== "疾病");
      diseaseResolution = resolveDiseaseQueries(disease, availableDiseases);

      const targetStatement = db.prepare(
        "select disease, target, source_file from disease_target where disease like ? and disease <> '' and target <> '' limit ?"
      );
      const diseaseHerbStatement = db.prepare(
        "select disease, herb, target from disease_herb_target where disease like ? and disease <> '' and target <> '' limit ?"
      );
      const directStatement = db.prepare(
        "select disease, herb, target from disease_herb_target where disease like ? and herb like ? and disease <> '' and herb <> '' and target <> '' limit ?"
      );

      for (const query of diseaseResolution.queries) {
        diseaseTargetRows.push(...asRows(targetStatement.all(`%${query}%`, limit)));
        diseaseHerbRows.push(...asRows(diseaseHerbStatement.all(`%${query}%`, limit)));
        for (const item of herbs) {
          directRows.push(...asRows(directStatement.all(`%${query}%`, `%${item}%`, limit)));
        }
      }
      diseaseTargetRows = uniqueRows(diseaseTargetRows, ["disease", "target", "source_file"]).slice(0, limit);
      diseaseHerbRows = uniqueRows(diseaseHerbRows, ["disease", "herb", "target"]).slice(0, limit);
      directRows = uniqueRows(directRows, ["disease", "herb", "target"]).slice(0, limit);
    } finally {
      db.close();
    }

    const herbTargets = new Map<string, TargetEvidence>();
    for (const row of herbRows) {
      for (const target of splitTargets(row.target)) {
        addEvidence(herbTargets, target, row, {
          component: clean(row.component),
          herb: clean(row.herb),
          source: clean(row.source)
        });
      }
    }

    const diseaseTargets = new Map<string, TargetEvidence>();
    for (const row of diseaseTargetRows) {
      addEvidence(diseaseTargets, clean(row.target), row, {
        disease: clean(row.disease),
        source: clean(row.source_file)
      });
    }
    for (const row of diseaseHerbRows) {
      addEvidence(diseaseTargets, clean(row.target), row, {
        disease: clean(row.disease),
        herb: clean(row.herb),
        source: "disease_herb_target"
      });
    }

    const directTargets = new Map<string, TargetEvidence>();
    for (const row of directRows) {
      addEvidence(directTargets, clean(row.target), row, {
        disease: clean(row.disease),
        herb: clean(row.herb),
        source: "disease_herb_target"
      });
    }

    const targetAnnotations = await prisma.target.findMany({
      include: { genes: true, pathways: true }
    });
    const annotationByName = new Map<string, (typeof targetAnnotations)[number]>();
    for (const target of targetAnnotations) {
      const symbolKey = normalizeTarget(target.symbol);
      const nameKey = normalizeTarget(target.name);
      if (symbolKey) annotationByName.set(symbolKey, target);
      if (nameKey) annotationByName.set(nameKey, target);
    }

    const strictKeys = Array.from(herbTargets.keys()).filter((key) => diseaseTargets.has(key));
    const directKeys = Array.from(directTargets.keys()).filter((key) => !strictKeys.includes(key));

    const targetRows = [...strictKeys, ...directKeys].map((key) => {
      const herbEvidence = herbTargets.get(key);
      const diseaseEvidence = diseaseTargets.get(key);
      const directEvidence = directTargets.get(key);
      const annotation = annotationByName.get(key);
      const pathways = annotation?.pathways.map((pathway) => pathway.name) ?? [];
      const genes = annotation?.genes.map((gene) => gene.symbol) ?? [];
      return {
        target: herbEvidence?.label ?? diseaseEvidence?.label ?? directEvidence?.label ?? key,
        normalizedTarget: key,
        matchType: strictKeys.includes(key) ? "严格交集" : "疾病-中药直接关联",
        targetName: annotation?.name ?? "",
        genes: genes.join("; "),
        pathways: pathways.join("; "),
        components: herbEvidence ? preview(herbEvidence.components, 20).join("; ") : "",
        herbs: preview(new Set([...(herbEvidence?.herbs ?? []), ...(directEvidence?.herbs ?? [])]), 20).join("; "),
        diseaseNames: preview(new Set([...(diseaseEvidence?.diseases ?? []), ...(directEvidence?.diseases ?? [])]), 10).join("; "),
        herbEvidenceCount: herbEvidence?.rows.length ?? 0,
        diseaseEvidenceCount: diseaseEvidence?.rows.length ?? 0,
        directEvidenceCount: directEvidence?.rows.length ?? 0,
        sources: preview(new Set([...(herbEvidence?.sources ?? []), ...(diseaseEvidence?.sources ?? []), ...(directEvidence?.sources ?? [])]), 20).join("; ")
      };
    });

    const componentScores = new Map<string, Set<string>>();
    for (const row of targetRows) {
      for (const component of row.components.split("; ").filter(Boolean)) {
        const targets = componentScores.get(component) ?? new Set<string>();
        targets.add(row.target);
        componentScores.set(component, targets);
      }
    }

    const pathwayScores = new Map<string, Set<string>>();
    for (const row of targetRows) {
      for (const pathway of row.pathways.split("; ").filter(Boolean)) {
        const targets = pathwayScores.get(pathway) ?? new Set<string>();
        targets.add(row.target);
        pathwayScores.set(pathway, targets);
      }
    }

    const componentChart = Array.from(componentScores, ([name, targets]) => ({ name, targets: targets.size }))
      .sort((a, b) => b.targets - a.targets)
      .slice(0, 20);
    const pathwayChart = Array.from(pathwayScores, ([name, targets]) => ({ name, targets: targets.size }))
      .sort((a, b) => b.targets - a.targets)
      .slice(0, 20);

    const summary = {
      herb,
      herbs,
      disease,
      herbTargetCount: herbTargets.size,
      diseaseTargetCount: diseaseTargets.size,
      strictIntersectionCount: strictKeys.length,
      directAssociationTargetCount: directTargets.size,
      candidateTargetCount: targetRows.length,
      componentCount: new Set(herbRows.map((row) => clean(row.component)).filter(Boolean)).size,
      pathwayCount: pathwayScores.size,
      rowLimit: limit,
      diseaseQueries: diseaseResolution.queries,
      matchedDiseaseNames: diseaseResolution.matchedNames
    };

    return NextResponse.json({
      ok: true,
      summary,
      charts: {
        overlap: [
          { name: "中药靶点", value: summary.herbTargetCount },
          { name: "疾病靶点", value: summary.diseaseTargetCount },
          { name: "严格交集", value: summary.strictIntersectionCount },
          { name: "直接关联", value: summary.directAssociationTargetCount }
        ],
        components: componentChart,
        pathways: pathwayChart
      },
      targets: targetRows,
      raw: {
        herbLinks: herbRows,
        diseaseTargets: diseaseTargetRows,
        diseaseHerbLinks: diseaseHerbRows,
        directDiseaseHerbLinks: directRows
      }
    });
  } catch (error) {
    return handleRouteError(error);
  }
}
