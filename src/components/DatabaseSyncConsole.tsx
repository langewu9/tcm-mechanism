"use client";

import { CheckCircle2, DatabaseZap, Play, Plus, TestTube2, Trash2, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

type SyncRun = {
  id: string;
  status: string;
  rowsRead: number;
  herbsSynced: number;
  compoundsSynced: number;
  targetsSynced: number;
  errorMessage: string | null;
  startedAt: Date | string;
};

type DatabaseSource = {
  id: string;
  name: string;
  driver: string;
  environmentVariable: string | null;
  enabled: boolean;
  syncCursor: number;
  lastConnectedAt: Date | string | null;
  lastSyncedAt: Date | string | null;
  syncRuns: SyncRun[];
};

async function requestJson(url: string, init?: RequestInit) {
  const response = await fetch(url, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}

export function DatabaseSyncConsole({ sources }: { sources: DatabaseSource[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [maxRows, setMaxRows] = useState("10000");

  async function createSource(formData: FormData) {
    setBusy("create");
    setMessage("");
    try {
      await requestJson("/api/admin/database-sources", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(Object.fromEntries(formData.entries()))
      });
      setMessage("数据源已保存。请先测试连接，再执行同步。");
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setBusy("");
    }
  }

  async function action(id: string, kind: "test" | "sync") {
    setBusy(`${kind}:${id}`);
    setMessage("");
    try {
      const data = await requestJson(`/api/admin/database-sources/${id}/${kind}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: kind === "sync" ? JSON.stringify({ maxRows: maxRows.trim() || null }) : undefined
      });
      setMessage(
        kind === "test"
          ? `连接成功：源表共 ${data.result.rowCount.toLocaleString()} 行。`
          : `同步完成：读取 ${data.result.rowsRead.toLocaleString()} 行，写入/更新 ${data.result.herbsSynced} 味中药、${data.result.compoundsSynced} 个成分、${data.result.targetsSynced} 个靶点。`
      );
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "操作失败");
      router.refresh();
    } finally {
      setBusy("");
    }
  }

  async function remove(id: string) {
    if (!window.confirm("删除该数据源及其同步历史？已同步的知识库数据不会被删除。")) return;
    setBusy(`delete:${id}`);
    try {
      await requestJson(`/api/admin/database-sources/${id}`, { method: "DELETE" });
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-5">
      <section className="panel p-5">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-pine text-white"><DatabaseZap size={20} /></span>
          <div>
            <h2 className="text-xl font-black">动态数据库接入与同步</h2>
            <p className="mt-1 text-sm leading-6 text-ink/60">运行时登记 SQLite 数据源，通过字段映射和持久化游标续传、幂等同步中药—成分—靶点关系。连接信息不会返回浏览器。</p>
          </div>
        </div>

        <form action={createSource} className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label className="text-sm font-bold">数据源名称<input className="field mt-1" name="name" placeholder="本地药理缓存库" required /></label>
          <label className="text-sm font-bold">SQLite 文件路径<input className="field mt-1" name="connectionUrl" defaultValue="data_cache.db" /></label>
          <label className="text-sm font-bold">或环境变量<input className="field mt-1" name="environmentVariable" placeholder="TCM_SOURCE_DATABASE" /></label>
          <label className="text-sm font-bold">源表<input className="field mt-1" name="table" defaultValue="herb_component_target" required /></label>
          <label className="text-sm font-bold">中药字段<input className="field mt-1" name="herbColumn" defaultValue="herb" required /></label>
          <label className="text-sm font-bold">成分字段<input className="field mt-1" name="compoundColumn" defaultValue="component" required /></label>
          <label className="text-sm font-bold">靶点字段<input className="field mt-1" name="targetColumn" defaultValue="target" required /></label>
          <div className="flex items-end"><button className="btn btn-primary w-full" disabled={Boolean(busy)}><Plus size={16} />添加数据源</button></div>
        </form>
      </section>

      <section className="panel p-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div><h3 className="text-lg font-black">已接入数据源</h3><p className="mt-1 text-xs text-ink/55">同步行数留空表示完整同步；先用小批量验证可缩短首次等待。</p></div>
          <label className="text-sm font-bold">本次最多读取行数<input className="field mt-1 w-48" inputMode="numeric" value={maxRows} onChange={(event) => setMaxRows(event.target.value)} placeholder="留空为全部" /></label>
        </div>

        {message ? <div className="mt-4 rounded-md border border-pine/15 bg-cloud p-3 text-sm font-semibold">{message}</div> : null}
        <div className="mt-4 space-y-4">
          {sources.length === 0 ? <p className="rounded-md bg-cloud p-4 text-sm text-ink/60">尚未登记数据源。</p> : sources.map((source) => {
            const latest = source.syncRuns[0];
            return (
              <article key={source.id} className="rounded-md border border-pine/12 bg-cloud/70 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2"><h4 className="font-black">{source.name}</h4><span className="rounded bg-pine/8 px-2 py-0.5 text-xs font-bold">{source.driver}</span></div>
                    <p className="mt-1 text-xs text-ink/55">{source.environmentVariable ? `连接来自环境变量 ${source.environmentVariable}` : "连接来自受保护的本地路径"} · 下次从 rowid {source.syncCursor + 1} 续传</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button className="btn btn-secondary" disabled={Boolean(busy)} onClick={() => action(source.id, "test")}><TestTube2 size={15} />{busy === `test:${source.id}` ? "测试中" : "测试连接"}</button>
                    <button className="btn btn-primary" disabled={Boolean(busy)} onClick={() => action(source.id, "sync")}><Play size={15} />{busy === `sync:${source.id}` ? "同步中" : "开始同步"}</button>
                    <button className="btn btn-secondary" aria-label="删除数据源" disabled={Boolean(busy)} onClick={() => remove(source.id)}><Trash2 size={15} /></button>
                  </div>
                </div>
                {latest ? (
                  <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-pine/10 pt-3 text-xs">
                    <span className="flex items-center gap-1 font-bold">{latest.status === "COMPLETED" ? <CheckCircle2 className="text-moss" size={15} /> : latest.status === "FAILED" ? <XCircle className="text-cinnabar" size={15} /> : <DatabaseZap size={15} />}{latest.status}</span>
                    <span>读取 {latest.rowsRead.toLocaleString()} 行</span><span>中药 {latest.herbsSynced}</span><span>成分 {latest.compoundsSynced}</span><span>靶点 {latest.targetsSynced}</span>
                    {latest.errorMessage ? <span className="text-cinnabar">{latest.errorMessage}</span> : null}
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}
