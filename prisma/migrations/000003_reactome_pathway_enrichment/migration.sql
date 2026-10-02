ALTER TABLE "Pathway" ADD COLUMN "source" TEXT NOT NULL DEFAULT 'LOCAL';
ALTER TABLE "Pathway" ADD COLUMN "externalId" TEXT;
ALTER TABLE "Pathway" ADD COLUMN "species" TEXT;
ALTER TABLE "Pathway" ADD COLUMN "sourceUrl" TEXT;
ALTER TABLE "Pathway" ADD COLUMN "lastSyncedAt" DATETIME;

CREATE UNIQUE INDEX "Pathway_externalId_key" ON "Pathway"("externalId");

CREATE TABLE "PathwayEnrichmentRun" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "herb" TEXT NOT NULL,
    "disease" TEXT NOT NULL,
    "source" TEXT NOT NULL DEFAULT 'REACTOME',
    "sourceVersion" TEXT,
    "sourceToken" TEXT,
    "inputCount" INTEGER NOT NULL,
    "identifiersFound" INTEGER NOT NULL,
    "identifiersNotFound" INTEGER NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "ownerId" TEXT NOT NULL,
    CONSTRAINT "PathwayEnrichmentRun_ownerId_fkey" FOREIGN KEY ("ownerId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX "PathwayEnrichmentRun_ownerId_createdAt_idx" ON "PathwayEnrichmentRun"("ownerId", "createdAt");

CREATE TABLE "PathwayEnrichmentItem" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "rank" INTEGER NOT NULL,
    "matchedEntities" INTEGER NOT NULL,
    "totalEntities" INTEGER NOT NULL,
    "coverage" REAL NOT NULL,
    "pValue" REAL NOT NULL,
    "fdr" REAL NOT NULL,
    "runId" TEXT NOT NULL,
    "pathwayId" TEXT NOT NULL,
    CONSTRAINT "PathwayEnrichmentItem_runId_fkey" FOREIGN KEY ("runId") REFERENCES "PathwayEnrichmentRun" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "PathwayEnrichmentItem_pathwayId_fkey" FOREIGN KEY ("pathwayId") REFERENCES "Pathway" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE UNIQUE INDEX "PathwayEnrichmentItem_runId_pathwayId_key" ON "PathwayEnrichmentItem"("runId", "pathwayId");
CREATE INDEX "PathwayEnrichmentItem_pathwayId_idx" ON "PathwayEnrichmentItem"("pathwayId");
