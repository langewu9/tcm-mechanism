import { AppShell } from "@/components/AppShell";
import { DatabaseSyncConsole } from "@/components/DatabaseSyncConsole";
import { ReactomeCatalogSync } from "@/components/ReactomeCatalogSync";
import { PageHeader } from "@/components/PageHeader";
import { ShieldCheck } from "lucide-react";
import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";

export default async function AdminPage() {
  const user = await requireAdmin();
  const [users, datasets, tasks, sources, reactomeCatalog] = await Promise.all([
    prisma.user.findMany({
      orderBy: { createdAt: "desc" },
      select: {
        id: true,
        name: true,
        email: true,
        role: true,
        createdAt: true,
        updatedAt: true,
        _count: { select: { datasets: true, cases: true, tasks: true } }
      }
    }),
    prisma.dataset.findMany({ orderBy: { createdAt: "desc" }, take: 10, include: { owner: { select: { name: true } } } }),
    prisma.analysisTask.findMany({ orderBy: { createdAt: "desc" }, take: 10, include: { owner: { select: { name: true } } } }),
    prisma.databaseSource.findMany({
      orderBy: { createdAt: "desc" },
      select: {
        id: true,
        name: true,
        driver: true,
        environmentVariable: true,
        enabled: true,
        syncCursor: true,
        lastConnectedAt: true,
        lastSyncedAt: true,
        syncRuns: { orderBy: { startedAt: "desc" }, take: 5 }
      }
    }),
    prisma.pathway.aggregate({
      where: { externalId: { startsWith: "R-HSA-" } },
      _count: { id: true },
      _max: { lastSyncedAt: true }
    })
  ]);

  return (
    <AppShell user={user}>
      <PageHeader eyebrow="Platform administration" title="系统与数据源管理" description="管理动态数据库接入、同步任务、平台账号和近期业务资产。" icon={ShieldCheck} action={<span className="status-badge status-success">管理员</span>} />
      <DatabaseSyncConsole sources={sources} />
      <div className="mt-5">
        <ReactomeCatalogSync catalog={{ count: reactomeCatalog._count.id, lastSyncedAt: reactomeCatalog._max.lastSyncedAt }} />
      </div>
      <UserManagement users={users} />
      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <Summary title="数据集" items={datasets.map((item) => ({ title: item.name, detail: `${item.owner.name} · ${item.rowCount} 行` }))} />
        <Summary title="分析任务" items={tasks.map((item) => ({ title: item.name, detail: `${item.owner.name} · ${item.status}` }))} />
      </div>
    </AppShell>
  );
}

function Summary({ title, items }: { title: string; items: Array<{ title: string; detail: string }> }) {
  return (
    <section className="panel p-5">
      <h2 className="text-lg font-black">{title}</h2>
      <div className="mt-4 space-y-3">
        {items.length ? (
          items.map((item, index) => (
            <div key={`${item.title}-${index}`} className="rounded-md bg-cloud p-3 text-sm">
              <p className="font-bold">{item.title}</p>
              <p className="text-ink/58">{item.detail}</p>
            </div>
          ))
        ) : (
          <p className="rounded-md bg-cloud p-4 text-sm text-ink/55">暂无记录</p>
        )}
      </div>
    </section>
  );
}

type AdminUser = {
  id: string;
  name: string;
  email: string;
  role: string;
  createdAt: Date;
  updatedAt: Date;
  _count: {
    datasets: number;
    cases: number;
    tasks: number;
  };
};

function UserManagement({ users }: { users: AdminUser[] }) {
  const adminCount = users.filter((item) => item.role === "ADMIN").length;
  const researcherCount = users.length - adminCount;

  return (
    <section className="panel mt-5 overflow-hidden">
      <div className="panel-header items-start">
        <div>
          <p className="page-kicker">USER MANAGEMENT</p>
          <h2 className="mt-1 text-xl font-black">用户管理</h2>
          <p className="section-help">按标准后台业务列表展示平台账号、角色权限、数据资产和最近更新时间。</p>
        </div>
        <div className="grid min-w-[16rem] grid-cols-3 gap-2 text-center text-sm">
          <Metric label="总用户" value={users.length} />
          <Metric label="管理员" value={adminCount} />
          <Metric label="研究员" value={researcherCount} />
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="data-table min-w-[980px]">
          <thead>
            <tr>
              <th>用户</th>
              <th>角色</th>
              <th>账号状态</th>
              <th>数据集</th>
              <th>医案</th>
              <th>分析任务</th>
              <th>注册时间</th>
              <th>最近更新</th>
            </tr>
          </thead>
          <tbody>
            {users.map((item) => (
              <tr key={item.id}>
                <td>
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="avatar h-9 w-9">{item.name.slice(0, 1).toUpperCase()}</span>
                    <span className="min-w-0">
                      <strong className="block overflow-hidden text-ellipsis whitespace-nowrap text-sm">{item.name}</strong>
                      <small className="block overflow-hidden text-ellipsis whitespace-nowrap text-ink/55">{item.email}</small>
                    </span>
                  </div>
                </td>
                <td><RoleBadge role={item.role} /></td>
                <td><span className="status-badge status-success">正常</span></td>
                <td>{item._count.datasets}</td>
                <td>{item._count.cases}</td>
                <td>{item._count.tasks}</td>
                <td>{formatDate(item.createdAt)}</td>
                <td>{formatDate(item.updatedAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!users.length ? (
        <div className="empty-state">
          <strong>暂无用户</strong>
          <p>用户注册后会在这里形成统一的账号列表，便于管理员进行权限和业务资产核对。</p>
        </div>
      ) : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-cinnabar/10 bg-cloud px-3 py-2">
      <strong className="block text-lg font-black">{value}</strong>
      <span className="text-xs text-ink/55">{label}</span>
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  const isAdmin = role === "ADMIN";

  return (
    <span className={`status-badge ${isAdmin ? "bg-cinnabar/10 text-cinnabar" : "status-success"}`}>
      {isAdmin ? "管理员" : "研究员"}
    </span>
  );
}

function formatDate(date: Date) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(date);
}
