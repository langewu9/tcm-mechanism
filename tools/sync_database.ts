import { prisma } from "../src/lib/prisma";
import { synchronizeDatabaseSource, testDatabaseSource } from "../src/lib/database-sync";

async function main() {
  const sourceName = process.argv[2] || "本地药理缓存库";
  const limitArg = process.argv[3];
  const maxRows = !limitArg || limitArg === "--all" ? undefined : Number(limitArg);
  const source = await prisma.databaseSource.findUnique({ where: { name: sourceName } });
  if (!source) throw new Error(`数据源不存在：${sourceName}`);

  const inspection = testDatabaseSource(source);
  console.log(`连接成功：${source.name}，源表 ${inspection.rowCount.toLocaleString()} 行`);
  const result = await synchronizeDatabaseSource(source, maxRows);
  console.log(
    `同步完成：读取 ${result.rowsRead.toLocaleString()} 行，中药 ${result.herbsSynced}，成分 ${result.compoundsSynced}，靶点 ${result.targetsSynced}`
  );
}

main()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
