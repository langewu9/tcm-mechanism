-- CreateTable
CREATE TABLE "DatabaseSource" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "driver" TEXT NOT NULL DEFAULT 'SQLITE',
    "connectionUrl" TEXT,
    "environmentVariable" TEXT,
    "mappingJson" TEXT NOT NULL,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "syncCursor" INTEGER NOT NULL DEFAULT 0,
    "lastConnectedAt" DATETIME,
    "lastSyncedAt" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);

-- CreateTable
CREATE TABLE "DatabaseSyncRun" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "sourceId" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'RUNNING',
    "rowsRead" INTEGER NOT NULL DEFAULT 0,
    "herbsSynced" INTEGER NOT NULL DEFAULT 0,
    "compoundsSynced" INTEGER NOT NULL DEFAULT 0,
    "targetsSynced" INTEGER NOT NULL DEFAULT 0,
    "errorMessage" TEXT,
    "startedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "finishedAt" DATETIME,
    CONSTRAINT "DatabaseSyncRun_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES "DatabaseSource" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE UNIQUE INDEX "DatabaseSource_name_key" ON "DatabaseSource"("name");
CREATE INDEX "DatabaseSyncRun_sourceId_startedAt_idx" ON "DatabaseSyncRun"("sourceId", "startedAt");
