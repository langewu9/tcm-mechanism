-- CreateTable
CREATE TABLE "User" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "passwordHash" TEXT NOT NULL,
    "role" TEXT NOT NULL DEFAULT 'RESEARCHER',
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);

-- CreateTable
CREATE TABLE "Dataset" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "filename" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "rowCount" INTEGER NOT NULL DEFAULT 0,
    "columnsJson" TEXT NOT NULL DEFAULT '[]',
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "ownerId" TEXT NOT NULL,
    CONSTRAINT "Dataset_ownerId_fkey" FOREIGN KEY ("ownerId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "DatasetRow" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "index" INTEGER NOT NULL,
    "dataJson" TEXT NOT NULL,
    "datasetId" TEXT NOT NULL,
    CONSTRAINT "DatasetRow_datasetId_fkey" FOREIGN KEY ("datasetId") REFERENCES "Dataset" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "MedicalCase" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "title" TEXT NOT NULL,
    "patientInfo" TEXT,
    "symptoms" TEXT NOT NULL,
    "tonguePulse" TEXT,
    "diagnosis" TEXT,
    "source" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "ownerId" TEXT NOT NULL,
    CONSTRAINT "MedicalCase_ownerId_fkey" FOREIGN KEY ("ownerId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "Syndrome" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "description" TEXT
);

-- CreateTable
CREATE TABLE "Formula" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "indication" TEXT
);

-- CreateTable
CREATE TABLE "Herb" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "meridian" TEXT,
    "effect" TEXT
);

-- CreateTable
CREATE TABLE "Compound" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "pubchemId" TEXT
);

-- CreateTable
CREATE TABLE "Target" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "symbol" TEXT NOT NULL,
    "name" TEXT
);

-- CreateTable
CREATE TABLE "Gene" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "symbol" TEXT NOT NULL,
    "name" TEXT
);

-- CreateTable
CREATE TABLE "Pathway" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "description" TEXT
);

-- CreateTable
CREATE TABLE "AnalysisTask" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'COMPLETED',
    "query" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    "ownerId" TEXT NOT NULL,
    "caseId" TEXT,
    CONSTRAINT "AnalysisTask_ownerId_fkey" FOREIGN KEY ("ownerId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "AnalysisTask_caseId_fkey" FOREIGN KEY ("caseId") REFERENCES "MedicalCase" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "AnalysisResult" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "summary" TEXT NOT NULL,
    "evidenceJson" TEXT NOT NULL,
    "networkJson" TEXT NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "taskId" TEXT NOT NULL,
    CONSTRAINT "AnalysisResult_taskId_fkey" FOREIGN KEY ("taskId") REFERENCES "AnalysisTask" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "_FormulaToSyndrome" (
    "A" TEXT NOT NULL,
    "B" TEXT NOT NULL,
    CONSTRAINT "_FormulaToSyndrome_A_fkey" FOREIGN KEY ("A") REFERENCES "Formula" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "_FormulaToSyndrome_B_fkey" FOREIGN KEY ("B") REFERENCES "Syndrome" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "_FormulaToHerb" (
    "A" TEXT NOT NULL,
    "B" TEXT NOT NULL,
    CONSTRAINT "_FormulaToHerb_A_fkey" FOREIGN KEY ("A") REFERENCES "Formula" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "_FormulaToHerb_B_fkey" FOREIGN KEY ("B") REFERENCES "Herb" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "_CompoundToHerb" (
    "A" TEXT NOT NULL,
    "B" TEXT NOT NULL,
    CONSTRAINT "_CompoundToHerb_A_fkey" FOREIGN KEY ("A") REFERENCES "Compound" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "_CompoundToHerb_B_fkey" FOREIGN KEY ("B") REFERENCES "Herb" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "_CompoundToTarget" (
    "A" TEXT NOT NULL,
    "B" TEXT NOT NULL,
    CONSTRAINT "_CompoundToTarget_A_fkey" FOREIGN KEY ("A") REFERENCES "Compound" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "_CompoundToTarget_B_fkey" FOREIGN KEY ("B") REFERENCES "Target" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "_GeneToTarget" (
    "A" TEXT NOT NULL,
    "B" TEXT NOT NULL,
    CONSTRAINT "_GeneToTarget_A_fkey" FOREIGN KEY ("A") REFERENCES "Gene" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "_GeneToTarget_B_fkey" FOREIGN KEY ("B") REFERENCES "Target" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "_PathwayToTarget" (
    "A" TEXT NOT NULL,
    "B" TEXT NOT NULL,
    CONSTRAINT "_PathwayToTarget_A_fkey" FOREIGN KEY ("A") REFERENCES "Pathway" ("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "_PathwayToTarget_B_fkey" FOREIGN KEY ("B") REFERENCES "Target" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateIndex
CREATE UNIQUE INDEX "User_email_key" ON "User"("email");

-- CreateIndex
CREATE UNIQUE INDEX "Syndrome_name_key" ON "Syndrome"("name");

-- CreateIndex
CREATE UNIQUE INDEX "Formula_name_key" ON "Formula"("name");

-- CreateIndex
CREATE UNIQUE INDEX "Herb_name_key" ON "Herb"("name");

-- CreateIndex
CREATE UNIQUE INDEX "Compound_name_key" ON "Compound"("name");

-- CreateIndex
CREATE UNIQUE INDEX "Target_symbol_key" ON "Target"("symbol");

-- CreateIndex
CREATE UNIQUE INDEX "Gene_symbol_key" ON "Gene"("symbol");

-- CreateIndex
CREATE UNIQUE INDEX "Pathway_name_key" ON "Pathway"("name");

-- CreateIndex
CREATE UNIQUE INDEX "AnalysisResult_taskId_key" ON "AnalysisResult"("taskId");

-- CreateIndex
CREATE UNIQUE INDEX "_FormulaToSyndrome_AB_unique" ON "_FormulaToSyndrome"("A", "B");

-- CreateIndex
CREATE INDEX "_FormulaToSyndrome_B_index" ON "_FormulaToSyndrome"("B");

-- CreateIndex
CREATE UNIQUE INDEX "_FormulaToHerb_AB_unique" ON "_FormulaToHerb"("A", "B");

-- CreateIndex
CREATE INDEX "_FormulaToHerb_B_index" ON "_FormulaToHerb"("B");

-- CreateIndex
CREATE UNIQUE INDEX "_CompoundToHerb_AB_unique" ON "_CompoundToHerb"("A", "B");

-- CreateIndex
CREATE INDEX "_CompoundToHerb_B_index" ON "_CompoundToHerb"("B");

-- CreateIndex
CREATE UNIQUE INDEX "_CompoundToTarget_AB_unique" ON "_CompoundToTarget"("A", "B");

-- CreateIndex
CREATE INDEX "_CompoundToTarget_B_index" ON "_CompoundToTarget"("B");

-- CreateIndex
CREATE UNIQUE INDEX "_GeneToTarget_AB_unique" ON "_GeneToTarget"("A", "B");

-- CreateIndex
CREATE INDEX "_GeneToTarget_B_index" ON "_GeneToTarget"("B");

-- CreateIndex
CREATE UNIQUE INDEX "_PathwayToTarget_AB_unique" ON "_PathwayToTarget"("A", "B");

-- CreateIndex
CREATE INDEX "_PathwayToTarget_B_index" ON "_PathwayToTarget"("B");

