import { NextResponse } from "next/server";

import { handleRouteError, jsonError, requireApiUser } from "@/lib/api";
import { prisma } from "@/lib/prisma";
import { parseUploadedTable } from "@/lib/upload";
import {
  buildProteomicsResult,
  parseProteomicsRows,
  resolveProteomicsMapping,
  type ProteomicsThresholds
} from "@/lib/proteomics";

export const runtime = "nodejs";
export const maxDuration = 300;

const MAX_ROWS = 25000;

function numberField(value: FormDataEntryValue | null, fallback: number, min: number, max: number) {
  const parsed = Number(value == null || value === "" ? fallback : value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(parsed, min), max);
}

function listField(value: FormDataEntryValue | null) {
  return String(value || "")
    .split(/[\s,，、;；|/]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 2000);
}

export async function GET() {
  try {
    const user = await requireApiUser();
    const items = await prisma.proteomicsDataset.findMany({
      where: user.role === "ADMIN" ? {} : { ownerId: user.id },
      orderBy: { createdAt: "desc" },
      include: {
        owner: { select: { name: true, email: true } },
        analyses: {
          orderBy: { createdAt: "desc" },
          take: 1,
          select: {
            id: true,
            name: true,
            status: true,
            selectedRowCount: true,
            normalizedCount: true,
            candidateOverlapCount: true,
            createdAt: true
          }
        }
      }
    });
    return NextResponse.json({ ok: true, items });
  } catch (error) {
    return handleRouteError(error);
  }
}

export async function POST(request: Request) {
  try {
    const user = await requireApiUser();
    const form = await request.formData();
    const file = form.get("file");
    if (!(file instanceof File)) return jsonError("请上传 CSV、XLS 或 XLSX 文件");

    const parsed = await parseUploadedTable(file);
    if (!parsed.columns.length || !parsed.rows.length) return jsonError("上传文件没有可分析的数据行");
    if (parsed.rows.length > MAX_ROWS) return jsonError(`单次最多分析 ${MAX_ROWS.toLocaleString()} 行，请先拆分文件`);

    const thresholds: ProteomicsThresholds = {
      log2FcMin: numberField(form.get("log2FcMin"), 1, 0, 100),
      fdrMax: numberField(form.get("fdrMax"), 0.05, 0, 1),
      pValueMax: numberField(form.get("pValueMax"), 0.05, 0, 1)
    };
    const mapping = resolveProteomicsMapping(parsed.columns, {
      geneColumn: String(form.get("geneColumn") || ""),
      proteinColumn: String(form.get("proteinColumn") || ""),
      log2FcColumn: String(form.get("log2FcColumn") || ""),
      pValueColumn: String(form.get("pValueColumn") || ""),
      fdrColumn: String(form.get("fdrColumn") || ""),
      directionColumn: String(form.get("directionColumn") || "")
    });
    const parsedRows = parseProteomicsRows(parsed.rows, mapping, thresholds);
    if (!parsedRows.selectedRows.length) return jsonError("没有行通过当前阈值，请降低 |log2FC| 或放宽 FDR/P 值阈值");

    const referenceTargets = listField(form.get("referenceTargets"));
    const [geneRecords, targetRecords] = await Promise.all([
      prisma.gene.findMany({ select: { symbol: true, name: true, externalId: true } }),
      prisma.target.findMany({ select: { symbol: true, pathways: { select: { name: true, externalId: true } } } })
    ]);
    const result = buildProteomicsResult({ selectedRows: parsedRows.selectedRows, referenceTargets, geneRecords, targetRecords });
    const name = String(form.get("name") || file.name.replace(/\.[^.]+$/, "")).trim() || "差异蛋白组学分析";
    const description = String(form.get("description") || "").trim() || null;
    const now = new Date();

    const saved = await prisma.$transaction(async (tx) => {
      const dataset = await tx.proteomicsDataset.create({
        data: {
          name,
          description,
          filename: file.name,
          type: file.type || "application/octet-stream",
          rowCount: parsedRows.parsedRows.length,
          columnsJson: JSON.stringify(parsed.columns),
          mappingJson: JSON.stringify(mapping),
          ownerId: user.id
        }
      });
      await tx.proteomicsRow.createMany({
        data: parsedRows.parsedRows.map((row) => {
          const selected = result.rows.find((item) => item.index === row.index);
          return {
            index: row.index,
            originalLabel: row.originalLabel,
            proteinName: row.proteinName,
            geneSymbol: selected?.symbol || null,
            log2FoldChange: row.log2FoldChange,
            pValue: row.pValue,
            fdr: row.fdr,
            direction: row.direction,
            dataJson: JSON.stringify(row.raw),
            datasetId: dataset.id
          };
        })
      });
      const analysis = await tx.proteomicsAnalysis.create({
        data: {
          name,
          status: "COMPLETED",
          log2FcMin: thresholds.log2FcMin,
          fdrMax: thresholds.fdrMax,
          pValueMax: thresholds.pValueMax,
          inputRowCount: parsedRows.parsedRows.length,
          selectedRowCount: result.summary.selectedRowCount,
          normalizedCount: result.summary.normalizedCount,
          unmappedCount: result.summary.unmappedCount,
          candidateOverlapCount: result.summary.candidateOverlapCount,
          sourceVersion: "LOCAL",
          resultJson: JSON.stringify({ ...result, datasetId: dataset.id }),
          finishedAt: now,
          ownerId: user.id,
          datasetId: dataset.id
        }
      });
      return { dataset, analysis };
    });

    return NextResponse.json({ ok: true, dataset: saved.dataset, analysis: { ...saved.analysis, result } });
  } catch (error) {
    return handleRouteError(error);
  }
}
