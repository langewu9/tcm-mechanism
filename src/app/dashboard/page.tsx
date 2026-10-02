import Link from "next/link";
import { ArrowRight, Database, FileSearch, FileText, FlaskConical, Leaf, Network, Pill, Route, Upload } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { prisma } from "@/lib/prisma";
import { requireUser } from "@/lib/auth";

export const runtime = "nodejs";

const actions = [
  { href: "/research", title: "开始药理检索", description: "查询疾病、中药、成分、靶点与 ChEMBL", icon: FileSearch },
  { href: "/datasets", title: "导入研究数据", description: "上传 CSV 或 Excel 并纳入数据管理", icon: Upload },
  { href: "/analysis", title: "创建分析任务", description: "从医案生成证候到通路的分析链路", icon: FlaskConical }
];

export default async function DashboardPage() {
  const user = await requireUser();
  const scope = user.role === "ADMIN" ? {} : { ownerId: user.id };
  const [datasets, cases, tasks, herbs, compounds, targets, pathways, latest] = await Promise.all([
    prisma.dataset.count({ where: scope }),
    prisma.medicalCase.count({ where: scope }),
    prisma.analysisTask.count({ where: scope }),
    prisma.herb.count(), prisma.compound.count(), prisma.target.count(), prisma.pathway.count(),
    prisma.analysisTask.findMany({ where: scope, orderBy: { createdAt: "desc" }, take: 5, include: { result: true } })
  ]);

  return (
    <AppShell user={user}>
      <div className="space-y-6">
        <PageHeader eyebrow="Workspace overview" title={`${user.name}，欢迎回来`} description="查看研究资产、知识库规模与近期任务，然后继续上一次研究工作。" action={<span className="status-badge status-success">本地知识库已连接</span>} />

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="研究数据集" value={datasets} icon={Database} />
          <StatCard label="医案记录" value={cases} icon={FileText} />
          <StatCard label="分析任务" value={tasks} icon={FlaskConical} />
          <StatCard label="知识节点" value={herbs + compounds + targets + pathways} icon={Network} />
        </div>

        <section className="panel overflow-hidden">
          <div className="panel-header"><div><h3 className="section-title-sm">常用操作</h3><p className="section-help">从高频任务开始工作</p></div></div>
          <div className="grid md:grid-cols-3">
            {actions.map((action, index) => <Link key={action.href} href={action.href} className={`dashboard-action group flex items-start gap-3 p-5 ${index ? "border-t border-cinnabar/10 md:border-l md:border-t-0" : ""}`}>
              <span className="dashboard-action-icon"><action.icon size={19} /></span>
              <span className="min-w-0 flex-1"><strong className="block text-sm">{action.title}</strong><small className="mt-1 block leading-5 text-ink/55">{action.description}</small></span><ArrowRight className="mt-1 text-ink/30 group-hover:text-cinnabar" size={17} />
            </Link>)}
          </div>
        </section>

        <div className="grid gap-5 xl:grid-cols-[1fr_340px]">
          <section className="panel overflow-hidden">
            <div className="panel-header"><div><h3 className="section-title-sm">最近分析</h3><p className="section-help">最近保存的五项任务</p></div><Link href="/analysis" className="text-xs font-bold text-cinnabar">查看全部</Link></div>
            {latest.length ? <div className="divide-y divide-cinnabar/10">{latest.map((task) => <Link href="/analysis" key={task.id} className="block px-5 py-4 hover:bg-cinnabar/5"><div className="flex items-center justify-between gap-3"><p className="truncate text-sm font-bold">{task.name}</p><time className="shrink-0 text-xs text-ink/45">{task.createdAt.toLocaleDateString("zh-CN")}</time></div><p className="mt-1 line-clamp-2 text-xs leading-5 text-ink/55">{task.result?.summary ?? task.query}</p></Link>)}</div> : <div className="empty-state min-h-56"><FlaskConical size={25} /><strong>暂无分析任务</strong><p>创建第一个任务后，分析摘要会出现在这里。</p></div>}
          </section>

          <section className="panel p-5">
            <h3 className="section-title-sm">知识库概览</h3><p className="section-help">已纳入分析链路的结构化实体</p>
            <dl className="mt-5 space-y-4">
              {[{ label: "中药", value: herbs, icon: Leaf }, { label: "活性成分", value: compounds, icon: Pill }, { label: "作用靶点", value: targets, icon: Network }, { label: "生物通路", value: pathways, icon: Route }].map((item) => <div key={item.label} className="knowledge-stat"><span><item.icon size={16} /></span><dt>{item.label}</dt><dd>{item.value.toLocaleString("zh-CN")}</dd></div>)}
            </dl>
          </section>
        </div>
      </div>
    </AppShell>
  );
}
