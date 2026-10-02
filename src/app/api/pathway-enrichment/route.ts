import { NextResponse } from "next/server";

import { handleRouteError, jsonError, requireApiUser } from "@/lib/api";
import { prisma } from "@/lib/prisma";
import { analyzeReactomePathways, normalizeEnrichmentTargets, resolveHumanGeneSymbols } from "@/lib/reactome";

export const runtime = "nodejs";

function text(value: unknown, field: string) {
  if (typeof value !== "string") throw new Error(`${field} 无效`);
  const result = value.trim();
  if (!result || result.length > 500) throw new Error(`${field} 无效`);
  return result;
}

export async function POST(request: Request) {
  try {
    const user = await requireApiUser();
    const body = await request.json();
    const targetLabels = normalizeEnrichmentTargets(body.targets);
    if (targetLabels.length < 2) return jsonError("至少需要 2 个候选靶点才能进行通路富集。");

    const herb = text(body.herb, "中药查询");
    const disease = text(body.disease, "疾病查询");
    const geneResolution = await resolveHumanGeneSymbols(targetLabels);
    if (geneResolution.symbols.length < 2) return jsonError("候选靶点未能规范化为足够的人类基因符号，无法进行通路富集。");
    const enrichment = await analyzeReactomePathways(geneResolution.symbols);
    const now = new Date();
    const existingTargets = await prisma.target.findMany({ select: { id: true, symbol: true } });
    const targetByNormalizedSymbol = new Map(existingTargets.map((target) => [target.symbol.trim().toUpperCase(), target]));

    const run = await prisma.$transaction(async (tx) => {
      const createdRun = await tx.pathwayEnrichmentRun.create({
        data: {
          herb,
          disease,
          source: "REACTOME",
          sourceVersion: enrichment.sourceVersion,
          sourceToken: enrichment.token,
          inputCount: geneResolution.symbols.length,
          rawTargetCount: targetLabels.length,
          identifiersFound: Math.max(0, geneResolution.symbols.length - enrichment.identifiersNotFound),
          identifiersNotFound: enrichment.identifiersNotFound,
          ownerId: user.id
        }
      });

      for (const mapping of geneResolution.mappings) {
        const gene = await tx.gene.upsert({
          where: { symbol: mapping.symbol },
          update: {
            name: mapping.name,
            source: "MYGENE",
            externalId: mapping.entrezGeneId,
            sourceUrl: mapping.entrezGeneId ? `https://mygene.info/v3/gene/${mapping.entrezGeneId}` : null,
            lastSyncedAt: now
          },
          create: {
            symbol: mapping.symbol,
            name: mapping.name,
            source: "MYGENE",
            externalId: mapping.entrezGeneId,
            sourceUrl: mapping.entrezGeneId ? `https://mygene.info/v3/gene/${mapping.entrezGeneId}` : null,
            lastSyncedAt: now
          }
        });
        const target = targetByNormalizedSymbol.get(mapping.query.toUpperCase());
        if (target) {
          await tx.target.update({ where: { id: target.id }, data: { genes: { connect: { id: gene.id } } } });
        }
      }

      const items = [];
      for (const [index, pathway] of enrichment.pathways.entries()) {
        const existing = await tx.pathway.findFirst({
          where: { OR: [{ externalId: pathway.stableId }, { name: pathway.name }] }
        });
        const savedPathway = existing
          ? await tx.pathway.update({
              where: { id: existing.id },
              data: {
                source: "REACTOME",
                externalId: pathway.stableId,
                species: pathway.species,
                sourceUrl: `https://reactome.org/PathwayBrowser/#/${pathway.stableId}`,
                lastSyncedAt: now,
                description: existing.description || "Reactome 人类生物通路"
              }
            })
          : await tx.pathway.create({
              data: {
                name: pathway.name,
                description: "Reactome 人类生物通路",
                source: "REACTOME",
                externalId: pathway.stableId,
                species: pathway.species,
                sourceUrl: `https://reactome.org/PathwayBrowser/#/${pathway.stableId}`,
                lastSyncedAt: now
              }
            });

        const item = await tx.pathwayEnrichmentItem.create({
          data: {
            rank: index + 1,
            matchedEntities: pathway.matchedEntities,
            totalEntities: pathway.totalEntities,
            coverage: pathway.coverage,
            pValue: pathway.pValue,
            fdr: pathway.fdr,
            runId: createdRun.id,
            pathwayId: savedPathway.id
          },
          include: { pathway: true }
        });
        items.push(item);
      }
      return { ...createdRun, items };
    });

    return NextResponse.json({
      ok: true,
      run: {
        id: run.id,
        source: run.source,
        sourceVersion: run.sourceVersion,
        sourceToken: run.sourceToken,
        rawTargetCount: run.rawTargetCount,
        inputCount: run.inputCount,
        identifiersFound: run.identifiersFound,
        identifiersNotFound: run.identifiersNotFound,
        createdAt: run.createdAt
      },
      pathways: run.items.map((item) => ({
        rank: item.rank,
        name: item.pathway.name,
        stableId: item.pathway.externalId,
        sourceUrl: item.pathway.sourceUrl,
        matchedEntities: item.matchedEntities,
        totalEntities: item.totalEntities,
        coverage: item.coverage,
        pValue: item.pValue,
        fdr: item.fdr
      }))
    });
  } catch (error) {
    return handleRouteError(error);
  }
}
