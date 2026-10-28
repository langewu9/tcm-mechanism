import { useEffect, useRef, useState } from "react";
import { createCatalogSnapshot, type CatalogSnapshotQuery } from "../api/catalog";
import { ApiError } from "../api/client";
import { RAnalysisGallery } from "./RAnalysisGallery";
import { RChartSource, RChartSourceProvider } from "./RChartSource";
import { SubviewTabs } from "./SubviewTabs";

/** Server re-resolves the query and verifies its fingerprint; never submit graph edges. */
export function CatalogRVisualization({ query }: { query: Omit<CatalogSnapshotQuery, "expectedSha256"> & { expectedSha256?: string } }) {
  const [taskId, setTaskId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [source, setSource] = useState("task");
  const [selected, setSelected] = useState(query.queryType === "comparison" ? "catalog_summary" : "evidence_network");
  const generation = useRef(0);
  const lock = useRef(false);
  const querySignature = JSON.stringify(query);
  const presets = query.queryType === "comparison" ? [["catalog_summary", "名称对照数量"]] : [
    ["evidence_network", "圆形证据网络"], ["catalog_summary", "实体与证据概览"], ["catalog_degree", "连接度 / 注释分布"],
  ];
  useEffect(() => {
    generation.current++; setTaskId(null); setError(""); setBusy(false); lock.current = false;
    setSelected(query.queryType === "comparison" ? "catalog_summary" : "evidence_network");
    return () => { generation.current++; };
  }, [querySignature]);
  async function prepare() {
    if (!query.expectedSha256 || lock.current) return;
    lock.current = true; setBusy(true); setError("");
    const current = generation.current;
    try {
      const task = await createCatalogSnapshot({ ...query, expectedSha256: query.expectedSha256 });
      if (generation.current === current) setTaskId(task.id);
    } catch (cause) {
      if (generation.current === current) setError(cause instanceof ApiError ? cause.message : "检索快照创建失败，请重试。");
    } finally {
      if (generation.current === current) { lock.current = false; setBusy(false); }
    }
  }
  return <section className="catalog-r-section" aria-label="检索结果 R 可视化">

    <h3 className="section-title-sm">检索结果图表</h3>
    <p className="section-help">{query.queryType === "comparison" ? "名称对照只比较名称，不代表化学结构鉴定；同族成分不计入精确交集。" : "查看关联网络和实体统计。本地通路注释不等同于富集分析。"}</p>
    {error && <p className="notice-error" role="alert">{error}</p>}
    {taskId ? <RAnalysisGallery key={taskId} taskId={taskId} initialSource={source} /> : <>
      <button className="btn btn-secondary" type="button" disabled={busy || !query.expectedSha256} onClick={() => void prepare()}>
        {busy ? "正在保存检索结果…" : "准备图表"}
      </button>
      {!query.expectedSha256 && <p className="notice-info">检索结果已过期，请重新检索。</p>}
      <RChartSourceProvider source={source} onChange={setSource}>
        <SubviewTabs label="选择检索演示图表" value={selected} onChange={setSelected} views={presets.map(([key, label]) => ({ key, label, content: <RChartSource chartKey={key}>
          <p className="notice-info">点击“准备图表”后，可根据本次检索结果绘图。</p>
        </RChartSource> }))} />
      </RChartSourceProvider>
    </>}
  </section>;
}
