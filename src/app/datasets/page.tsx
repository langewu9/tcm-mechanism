import { Database, FileSpreadsheet } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { DatasetUploader } from "@/components/DatasetUploader";
import { DeleteButton } from "@/components/DeleteButton";
import { requireUser } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";

export default async function DatasetsPage() {
  const user = await requireUser();
  const items = await prisma.dataset.findMany({
    where: user.role === "ADMIN" ? {} : { ownerId: user.id },
    orderBy: { createdAt: "desc" },
    include: { owner: { select: { name: true } }, rows: { take: 3, orderBy: { index: "asc" } } }
  });
  return (
    <AppShell user={user}>
      <PageHeader eyebrow="Data assets" title="研究数据资产" description="导入、追踪并管理用于检索与分析的 CSV、Excel 数据集。" icon={Database} action={<span className="status-badge status-success">{items.length} 个数据集</span>} />
      <div className="grid gap-5 xl:grid-cols-[380px_minmax(0,1fr)]">
        <DatasetUploader />
        <section className="panel overflow-hidden">
          <div className="panel-header"><div><h2 className="section-title-sm">数据集列表</h2><p className="section-help">按最近导入时间排序，删除操作不会影响原始源文件。</p></div></div>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="py-2">名称</th>
                  <th>文件</th>
                  <th>行数</th>
                  <th>上传人</th>
                  <th>导入时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-pine/10">
                {items.map((item) => (
                  <tr key={item.id}>
                    <td className="py-3 font-bold">{item.name}</td>
                    <td>{item.filename}</td>
                    <td>{item.rowCount}</td>
                    <td>{item.owner.name}</td>
                    <td>{item.createdAt.toLocaleDateString("zh-CN")}</td>
                    <td><DeleteButton endpoint={`/api/datasets/${item.id}`} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!items.length ? <div className="empty-state"><FileSpreadsheet size={26} /><strong>暂无数据集</strong><p>从左侧导入第一份 CSV 或 Excel 文件，系统会记录数据行数和上传人。</p></div> : null}
        </section>
      </div>
    </AppShell>
  );
}
