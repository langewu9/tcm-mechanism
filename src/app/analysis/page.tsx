import { FlaskConical, History } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { AnalysisWorkbench } from "@/components/AnalysisWorkbench";
import { requireUser } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";

export default async function AnalysisPage() {
  const user = await requireUser();
  const cases = await prisma.medicalCase.findMany({
    where: user.role === "ADMIN" ? {} : { ownerId: user.id },
    orderBy: { createdAt: "desc" },
    select: { id: true, title: true, symptoms: true }
  });
  const tasks = await prisma.analysisTask.findMany({
    where: user.role === "ADMIN" ? {} : { ownerId: user.id },
    orderBy: { createdAt: "desc" },
    take: 8,
    include: { result: true }
  });
  return (
    <AppShell user={user}>
      <PageHeader eyebrow="AI analysis" title="证候与网络药理智能分析" description="从医案或研究问题生成证候、方药、成分、靶点与通路的结构化证据链。" icon={FlaskConical} action={<span className="status-badge status-success">结果自动保存</span>} />
      <AnalysisWorkbench cases={cases} />
      <section className="panel mt-6 overflow-hidden">
        <div className="panel-header"><div><h2 className="section-title-sm">已保存结果</h2><p className="section-help">最近八项分析任务，可用于回顾研究假设和证据摘要。</p></div><History size={18} className="text-cinnabar" /></div>
        <div className="divide-y divide-pine/10">
          {tasks.map((task) => (
            <article key={task.id} className="saved-analysis">
              <div><p>{task.name}</p><time>{task.createdAt.toLocaleDateString("zh-CN")}</time></div>
              <span>{task.result?.summary || task.query}</span>
            </article>
          ))}
          {!tasks.length ? <div className="empty-state min-h-48"><FlaskConical size={24} /><strong>暂无保存结果</strong><p>完成第一项分析后，结果摘要会出现在这里。</p></div> : null}
        </div>
      </section>
    </AppShell>
  );
}
