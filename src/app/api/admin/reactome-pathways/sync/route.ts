import { NextResponse } from "next/server";

import { handleRouteError, requireApiAdmin } from "@/lib/api";
import { prisma } from "@/lib/prisma";
import { fetchReactomeHumanPathwayCatalog } from "@/lib/reactome";

export const runtime = "nodejs";
export const maxDuration = 300;

const BATCH_SIZE = 100;

export async function POST() {
  try {
    await requireApiAdmin();
    const { pathways, sourceVersion } = await fetchReactomeHumanPathwayCatalog();
    const now = new Date();
    const nameCounts = new Map<string, number>();
    for (const pathway of pathways) nameCounts.set(pathway.name, (nameCounts.get(pathway.name) ?? 0) + 1);
    const existing = await prisma.pathway.findMany({
      select: { id: true, name: true, externalId: true }
    });
    const byExternalId = new Map(existing.filter((item) => item.externalId).map((item) => [item.externalId!, item]));
    const byName = new Map(existing.map((item) => [item.name, item]));
    let created = 0;
    let updated = 0;

    for (let start = 0; start < pathways.length; start += BATCH_SIZE) {
      const batch = pathways.slice(start, start + BATCH_SIZE);
      const operations = batch.map((pathway) => {
        // Reactome contains a small number of distinct stable records with the
        // same display name. The local model keeps names unique, so preserve all
        // records by adding the stable ID only when a name is genuinely repeated.
        const name = nameCounts.get(pathway.name)! > 1 ? `${pathway.name} [${pathway.stableId}]` : pathway.name;
        const previous = byExternalId.get(pathway.stableId) ?? byName.get(name);
        const data = {
          name,
          description: "Reactome 人类生物通路目录",
          source: "REACTOME",
          externalId: pathway.stableId,
          species: pathway.species,
          sourceUrl: `https://reactome.org/PathwayBrowser/#/${pathway.stableId}`,
          lastSyncedAt: now
        };
        if (previous) {
          updated += 1;
          return prisma.pathway.update({ where: { id: previous.id }, data });
        }
        created += 1;
        return prisma.pathway.create({ data });
      });
      await prisma.$transaction(operations);
    }

    const totalHumanPathways = await prisma.pathway.count({ where: { externalId: { startsWith: "R-HSA-" } } });
    return NextResponse.json({
      ok: true,
      result: { catalogTotal: pathways.length, totalHumanPathways, created, updated, sourceVersion, syncedAt: now.toISOString() }
    });
  } catch (error) {
    return handleRouteError(error);
  }
}
