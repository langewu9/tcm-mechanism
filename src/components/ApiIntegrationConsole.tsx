"use client";

import { Activity, Bot, CheckCircle2, DatabaseZap, FlaskConical, Network, Play, RefreshCw, Search, XCircle } from "lucide-react";
import { useMemo, useState } from "react";

type TestTarget = "qwen" | "disease" | "herb" | "component" | "chembl" | "intersection" | "compare" | "scientist";

type IntegrationResult = {
  ok: boolean;
  status: number;
  url: string;
  data: unknown;
  error?: string;
  elapsedMs: number;
};

const tests: Array<{
  id: TestTarget;
  title: string;
  desc: string;
  icon: typeof Activity;
}> = [
  { id: "qwen", title: "Qwen / BianCang", desc: "测试百炼或本地 OpenAI 兼容模型接口", icon: Bot },
  { id: "disease", title: "疾病证据检索", desc: "Pulmonary fibrosis -> 中药与疾病靶点", icon: Search },
  { id: "herb", title: "中药证据检索", desc: "粳米 -> 成分与靶点", icon: DatabaseZap },
  { id: "component", title: "成分靶点检索", desc: "quercetin -> 来源与靶点", icon: Activity },
  { id: "chembl", title: "ChEMBL 本地库", desc: "quercetin -> ChEMBL 分子记录", icon: FlaskConical },
  { id: "intersection", title: "靶点交集", desc: "疾病侧靶点 vs 方剂侧靶点", icon: Network },
  { id: "compare", title: "成分比对", desc: "实验检测成分 vs 数据库汇总", icon: CheckCircle2 },
  { id: "scientist", title: "AI Scientist", desc: "生成可验证研究计划样例", icon: Bot }
];

function summarize(value: unknown) {
  if (!value || typeof value !== "object") return "暂无返回数据";
  const data = value as Record<string, any>;
  if (Array.isArray(data.items)) return `返回 ${data.items.length} 条记录`;
  if (Array.isArray(data.herbs) || Array.isArray(data.targets)) {
    return `中药 ${data.herbs?.length ?? 0} 项，靶点 ${data.targets?.length ?? 0} 项`;
  }
  if (typeof data.intersection_count === "number") return `共同靶点 ${data.intersection_count} 个`;
  if (typeof data.match_rate === "number") return `匹配率 ${data.match_rate}%`;
  if (typeof data.paper_title === "string") return data.paper_title;
  if (typeof data.content === "string") return data.content.slice(0, 80);
  if (typeof data.error === "string") return data.error;
  return "已返回结构化数据";
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-md border border-[#eadac6] bg-[#fffaf1]/72 p-3 text-xs leading-5 text-[#4f3d31]">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function ApiIntegrationConsole() {
  const [status, setStatus] = useState<any>(null);
  const [active, setActive] = useState<TestTarget>("disease");
  const [results, setResults] = useState<Partial<Record<TestTarget, IntegrationResult>>>({});
  const [loading, setLoading] = useState<string>("");

  const activeResult = results[active];
  const passedCount = useMemo(() => Object.values(results).filter((item) => item?.ok).length, [results]);

  async function refreshStatus() {
    setLoading("status");
    try {
      const response = await fetch("/api/integrations/status", { cache: "no-store" });
      setStatus(await response.json());
    } finally {
      setLoading("");
    }
  }

  async function runTest(target: TestTarget) {
    setActive(target);
    setLoading(target);
    try {
      const response = await fetch("/api/integrations/test", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ target })
      });
      const data = await response.json();
      setResults((items) => ({ ...items, [target]: data.result }));
    } finally {
      setLoading("");
    }
  }

  async function runAll() {
    for (const item of tests) {
      await runTest(item.id);
    }
  }

  return (
    <div className="space-y-5">
      <section className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-black tracking-[0.22em] text-cinnabar">API CONNECTION</p>
            <h2 className="mt-2 text-2xl font-black md:text-3xl">完整 API 接入控制台</h2>
            <p className="mt-2 max-w-3xl text-sm leading-7 text-ink/62">
              统一检测 Next.js 全栈站点到 FastAPI 数据服务、本地 ChEMBL、Qwen/BianCang 和 AI Scientist
              的接口链路。此页会真实请求后端，不是静态说明。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-secondary" onClick={refreshStatus} disabled={loading === "status"}>
              <RefreshCw size={16} />
              刷新状态
            </button>
            <button className="btn btn-primary" onClick={runAll} disabled={Boolean(loading)}>
              <Play size={16} />
              一键测试全部
            </button>
          </div>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <section className="panel p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h3 className="text-lg font-black">接入端点</h3>
            <span className="rounded-sm border border-[#eadac6] bg-[#fffaf1]/72 px-2 py-1 text-xs font-bold text-cinnabar">
              已通过 {passedCount}/{tests.length}
            </span>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {tests.map((item) => {
              const Icon = item.icon;
              const result = results[item.id];
              const isActive = active === item.id;
              return (
                <button
                  key={item.id}
                  className={`rounded-md border p-4 text-left transition hover:-translate-y-0.5 ${
                    isActive ? "border-cinnabar bg-[#fff4e9]" : "border-[#eadac6] bg-[#fffaf1]/65"
                  }`}
                  onClick={() => runTest(item.id)}
                  disabled={Boolean(loading)}
                >
                  <div className="flex items-start gap-3">
                    <span className="grid h-9 w-9 shrink-0 place-items-center rounded-sm bg-cinnabar text-white">
                      <Icon size={17} />
                    </span>
                    <span>
                      <span className="block font-black">{item.title}</span>
                      <span className="mt-1 block text-xs leading-5 text-ink/56">{item.desc}</span>
                      <span className="mt-3 inline-flex items-center gap-1 text-xs font-bold">
                        {loading === item.id ? (
                          "测试中..."
                        ) : result ? (
                          result.ok ? (
                            <>
                              <CheckCircle2 size={14} className="text-cinnabar" />
                              {result.status} · {result.elapsedMs}ms
                            </>
                          ) : (
                            <>
                              <XCircle size={14} className="text-red-700" />
                              失败 · {result.error || result.status}
                            </>
                          )
                        ) : (
                          "等待测试"
                        )}
                      </span>
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        <section className="panel p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h3 className="text-lg font-black">当前结果</h3>
            <span className="text-xs font-bold text-ink/50">{active}</span>
          </div>
          {activeResult ? (
            <div className="space-y-3">
              <div className="rounded-md border border-[#eadac6] bg-[#fffaf1]/72 p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-black">{activeResult.ok ? "接口调用成功" : "接口调用失败"}</p>
                  <span className="text-xs font-bold text-ink/55">{activeResult.elapsedMs}ms</span>
                </div>
                <p className="mt-2 text-sm leading-6 text-ink/62">{summarize(activeResult.data)}</p>
                <p className="mt-2 break-all text-xs text-ink/45">{activeResult.url}</p>
              </div>
              <JsonBlock value={activeResult} />
            </div>
          ) : (
            <div className="rounded-md border border-dashed border-[#eadac6] bg-[#fffaf1]/55 p-8 text-sm leading-7 text-ink/55">
              选择左侧任一端点或点击“一键测试全部”，这里会显示真实返回、耗时、HTTP 状态和接口地址。
            </div>
          )}
        </section>
      </div>

      <section className="panel p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h3 className="text-lg font-black">服务总览</h3>
          <span className="text-xs text-ink/50">Next.js API Routes → FastAPI → 本地数据库/模型</span>
        </div>
        {status ? <JsonBlock value={status} /> : <p className="text-sm text-ink/58">点击“刷新状态”查看服务总览。</p>}
      </section>
    </div>
  );
}
