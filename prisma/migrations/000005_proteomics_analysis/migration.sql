-- CreateTable
CREATE TABLE "ProteomicsDataset" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "filename" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "rowCount" INTEGER NOT NULL DEFAULT 0,
    "columnsJson" TEXT NOT NULL DEFAULT '[]',
    "mappingJson" TEXT NOT NULL DEFAULT '{}',
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "ownerId" TEXT NOT NULL,
    CONSTRAINT "ProteomicsDataset_ownerId_fkey" FOREIGN KEY ("ownerId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "ProteomicsRow" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "index" INTEGER NOT NULL,
    "originalLabel" TEXT NOT NULL,
    "proteinName" TEXT,
    "geneSymbol" TEXT,
    "log2FoldChange" REAL,
    "pValue" REAL,
    "fdr" REAL,
    "direction" TEXT,
    "dataJson" TEXT NOT NULL,
    "datasetId" TEXT NOT NULL,
    CONSTRAINT "ProteomicsRow_datasetId_fkey" FOREIGN KEY ("datasetId") REFERENCES "ProteomicsDataset" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "ProteomicsAnalysis" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'COMPLETED',
    "log2FcMin" REAL NOT NULL DEFAULT 1,
    "fdrMax" REAL NOT NULL DEFAULT 0.05,
    "pValueMax" REAL NOT NULL DEFAULT 0.05,
    "inputRowCount" INTEGER NOT NULL DEFAULT 0,
    "selectedRowCount" INTEGER NOT NULL DEFAULT 0,
    "normalizedCount" INTEGER NOT NULL DEFAULT 0,
    "unmappedCount" INTEGER NOT NULL DEFAULT 0,
    "candidateOverlapCount" INTEGER NOT NULL DEFAULT 0,
    "sourceVersion" TEXT,
    "resultJson" TEXT NOT NULL,
    "errorMessage" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "finishedAt" DATETIME,
    "ownerId" TEXT NOT NULL,
    "datasetId" TEXT NOT NULL,
    CONSTRAINT "ProteomicsAnalysis_ownerId_fkey" FOREIGN KEY ("ownerId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "ProteomicsAnalysis_datasetId_fkey" FOREIGN KEY ("datasetId") REFERENCES "ProteomicsDataset" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateIndex
CREATE INDEX "ProteomicsDataset_ownerId_createdAt_idx" ON "ProteomicsDataset"("ownerId", "createdAt");
CREATE UNIQUE INDEX "ProteomicsRow_datasetId_index_key" ON "ProteomicsRow"("datasetId", "index");
CREATE INDEX "ProteomicsRow_datasetId_geneSymbol_idx" ON "ProteomicsRow"("datasetId", "geneSymbol");
CREATE INDEX "ProteomicsAnalysis_ownerId_createdAt_idx" ON "ProteomicsAnalysis"("ownerId", "createdAt");
CREATE INDEX "ProteomicsAnalysis_datasetId_createdAt_idx" ON "ProteomicsAnalysis"("datasetId", "createdAt");
