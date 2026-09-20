"use client";

import { CheckCircle2, Route, RotateCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

type CatalogState = {
  count: number;
  lastSyncedAt: Date | string | null;
};

export function ReactomeCatalogSync({ catalog }: { catalog: CatalogState }) {
  const router = useRouter();
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState("");

  async function synchronize() {
    setSyncing(true);
    setMessage("");
    try {
      const response = await fetch("/api/admin/reactome-pathways/sync", { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok === false) throw new Error(data.error || "通路目录同步失败。");
      const result = data.result;
      setMessage(`同步完成：Reactome v${result.sourceVersion || "未知"} 人类目录共 ${result.catalogTotal.toLocaleString()} 条；新增 ${result.created.toLocaleString()} 条，更新 ${result.updated.toLocaleString()} 条。`);
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "通路目录同步失败。");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <section className="panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-cinnabar text-white"><Route size={20} /></span>
          <div>
            <p className="page-kicker">REACTOME CATALOG</p>
            <h2 className="mt-1 text-xl font-black">人类生物通路目录</h2>
            <p className="mt-1 text-sm leading-6 text-ink/60">同步 Reactome 官方人类通路目录；与配方查询的富集结果分开管理，按稳定 ID 可追溯更新。</p>
          </div>
        </div>
        <button type="button" className="btn btn-primary" disabled={syncing} onClick={synchronize}>
          <RotateCw size={16} className={syncing ? "animate-spin" : ""} /> {syncing ? "正在同步目录..." : "同步 Reactome 人类目录"}
        </button>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-md bg-cloud px-4 py-3"><span className="block text-xs font-bold text-ink/55">已入库人类通路</span><strong className="mt-1 block text-2xl font-black">{catalog.count.toLocaleString()}</strong></div>
        <div className="rounded-md bg-cloud px-4 py-3"><span className="block text-xs font-bold text-ink/55">最近目录同步</span><strong className="mt-1 block text-sm font-black">{catalog.lastSyncedAt ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(catalog.lastSyncedAt)) : "尚未同步"}</strong></div>
      </div>
      {message ? <p className="mt-4 flex items-start gap-2 rounded-md border border-pine/15 bg-cloud p-3 text-sm font-semibold"><CheckCircle2 className="mt-0.5 shrink-0 text-moss" size={16} />{message}</p> : null}
    </section>
  );
}
