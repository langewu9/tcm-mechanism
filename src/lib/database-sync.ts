import { existsSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";

import { prisma } from "@/lib/prisma";

export const DEFAULT_DATABASE_MAPPING = {
  table: "herb_component_target",
  herbColumn: "herb",
  compoundColumn: "component",
  targetColumn: "target"
};

export type DatabaseMapping = typeof DEFAULT_DATABASE_MAPPING;

type SourceConfig = {
  id: string;
  driver: string;
  connectionUrl: string | null;
  environmentVariable: string | null;
  mappingJson: string;
  enabled: boolean;
  syncCursor: number;
};

const IDENTIFIER = /^[\p{L}\p{N}_]+$/u;

function identifier(value: string) {
  if (!IDENTIFIER.test(value)) throw new Error(`非法表名或字段名：${value}`);
  return `"${value.replaceAll('"', '""')}"`;
}

export function parseMapping(value: string | DatabaseMapping): DatabaseMapping {
  const parsed = typeof value === "string" ? JSON.parse(value) : value;
  for (const key of ["table", "herbColumn", "compoundColumn", "targetColumn"] as const) {
    if (typeof parsed[key] !== "string" || !IDENTIFIER.test(parsed[key])) {
      throw new Error(`同步映射 ${key} 无效`);
    }
  }
  return parsed;
}

function resolveConnection(source: SourceConfig) {
  if (source.driver !== "SQLITE") {
    throw new Error(`当前部署未启用 ${source.driver} 驱动`);
  }

  let connection = source.connectionUrl?.trim();
  if (source.environmentVariable) {
    if (!/^[A-Z][A-Z0-9_]*$/.test(source.environmentVariable)) {
      throw new Error("环境变量名称无效");
    }
    connection = process.env[source.environmentVariable]?.trim();
    if (!connection) throw new Error(`环境变量 ${source.environmentVariable} 未配置`);
  }
  if (!connection) throw new Error("未配置数据库连接");

  const rawPath = connection.startsWith("file:") ? connection.slice(5) : connection;
  const decodedPath = decodeURIComponent(rawPath);
  const databasePath = isAbsolute(decodedPath) ? decodedPath : resolve(process.cwd(), decodedPath);
  if (!existsSync(databasePath)) throw new Error(`数据库文件不存在：${databasePath}`);
  return databasePath;
}

function openSource(source: SourceConfig) {
  return new DatabaseSync(resolveConnection(source), { readOnly: true });
}

function inspect(db: DatabaseSync, mapping: DatabaseMapping) {
  const table = identifier(mapping.table);
  const row = db.prepare(`SELECT COUNT(*) AS count FROM ${table}`).get() as { count: number | bigint };
  const columns = db.prepare(`PRAGMA table_info(${table})`).all() as Array<{ name: string }>;
  const names = new Set(columns.map((column) => column.name));
  for (const column of [mapping.herbColumn, mapping.compoundColumn, mapping.targetColumn]) {
    if (!names.has(column)) throw new Error(`数据表 ${mapping.table} 缺少字段 ${column}`);
  }
  return { rowCount: Number(row.count), columns: [...names] };
}

export function testDatabaseSource(source: SourceConfig) {
  if (!source.enabled) throw new Error("该数据源已停用");
  const mapping = parseMapping(source.mappingJson);
  const db = openSource(source);
  try {
    return { ...inspect(db, mapping), mapping };
  } finally {
    db.close();
  }
}

function clean(value: unknown) {
  return value == null ? "" : String(value).trim();
}

function splitTargets(value: unknown) {
  return clean(value)
    .split(/[;,，；/|]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export async function synchronizeDatabaseSource(source: SourceConfig, maxRows?: number) {
  if (!source.enabled) throw new Error("该数据源已停用");
  if (maxRows !== undefined && (!Number.isInteger(maxRows) || maxRows < 1)) {
    throw new Error("maxRows 必须是正整数");
  }

  const run = await prisma.databaseSyncRun.create({ data: { sourceId: source.id } });
  const herbsSeen = new Set<string>();
  const compoundsSeen = new Set<string>();
  const targetsSeen = new Set<string>();
  let rowsRead = 0;
  let cursor = source.syncCursor;
  let db: DatabaseSync | undefined;

  try {
    const mapping = parseMapping(source.mappingJson);
    db = openSource(source);
    inspect(db, mapping);

    const table = identifier(mapping.table);
    const herbColumn = identifier(mapping.herbColumn);
    const compoundColumn = identifier(mapping.compoundColumn);
    const targetColumn = identifier(mapping.targetColumn);
    const statement = db.prepare(
      `SELECT rowid AS __rowid, ${herbColumn} AS herb, ${compoundColumn} AS compound, ${targetColumn} AS target ` +
        `FROM ${table} WHERE rowid > ? ORDER BY rowid LIMIT ?`
    );
    const batchSize = 250;

    while (maxRows === undefined || rowsRead < maxRows) {
      const take = Math.min(batchSize, maxRows === undefined ? batchSize : maxRows - rowsRead);
      const rows = statement.all(cursor, take) as Array<{
        __rowid: number | bigint;
        herb: unknown;
        compound: unknown;
        target: unknown;
      }>;
      if (!rows.length) break;
      cursor = Number(rows.at(-1)!.__rowid);
      rowsRead += rows.length;

      const herbs = new Set<string>();
      const targets = new Set<string>();
      const compoundLinks = new Map<string, { herbs: Set<string>; targets: Set<string> }>();

      for (const row of rows) {
        const herb = clean(row.herb);
        const compound = clean(row.compound);
        const rowTargets = splitTargets(row.target);
        if (herb) {
          herbs.add(herb);
          herbsSeen.add(herb);
        }
        for (const target of rowTargets) {
          targets.add(target);
          targetsSeen.add(target);
        }
        if (!compound) continue;
        compoundsSeen.add(compound);
        const links = compoundLinks.get(compound) ?? { herbs: new Set<string>(), targets: new Set<string>() };
        if (herb) links.herbs.add(herb);
        rowTargets.forEach((target) => links.targets.add(target));
        compoundLinks.set(compound, links);
      }

      const herbOperations = [...herbs].map((name) => prisma.herb.upsert({ where: { name }, update: {}, create: { name } }));
      const targetOperations = [...targets].map((symbol) => prisma.target.upsert({ where: { symbol }, update: {}, create: { symbol } }));
      if (herbOperations.length) await prisma.$transaction(herbOperations);
      if (targetOperations.length) await prisma.$transaction(targetOperations);

      const compoundOperations = [...compoundLinks].map(([name, links]) => {
          const relationData = {
            herbs: { connect: [...links.herbs].map((herbName) => ({ name: herbName })) },
            targets: { connect: [...links.targets].map((symbol) => ({ symbol })) }
          };
          return prisma.compound.upsert({
            where: { name },
            update: relationData,
            create: { name, ...relationData }
          });
        });
      if (compoundOperations.length) await prisma.$transaction(compoundOperations);

      if (rowsRead % 5000 === 0) {
        await Promise.all([
          prisma.databaseSyncRun.update({
            where: { id: run.id },
            data: {
              rowsRead,
              herbsSynced: herbsSeen.size,
              compoundsSynced: compoundsSeen.size,
              targetsSynced: targetsSeen.size
            }
          }),
          prisma.databaseSource.update({ where: { id: source.id }, data: { syncCursor: cursor } })
        ]);
      }
    }

    const finishedAt = new Date();
    const result = await prisma.databaseSyncRun.update({
      where: { id: run.id },
      data: {
        status: "COMPLETED",
        rowsRead,
        herbsSynced: herbsSeen.size,
        compoundsSynced: compoundsSeen.size,
        targetsSynced: targetsSeen.size,
        finishedAt
      }
    });
    await prisma.databaseSource.update({
      where: { id: source.id },
      data: { lastConnectedAt: finishedAt, lastSyncedAt: finishedAt, syncCursor: cursor }
    });
    return result;
  } catch (error) {
    const message = error instanceof Error ? error.message : "未知同步错误";
    await prisma.databaseSyncRun.update({
      where: { id: run.id },
      data: {
        status: "FAILED",
        rowsRead,
        herbsSynced: herbsSeen.size,
        compoundsSynced: compoundsSeen.size,
        targetsSynced: targetsSeen.size,
        errorMessage: message.slice(0, 2000),
        finishedAt: new Date()
      }
    });
    throw error;
  } finally {
    db?.close();
  }
}
