import { useEffect, useState } from "react";

type DemoChart = { key: string; label: string; rendererVersion: string };
type Manifest = { synthetic: boolean; disclaimer: string; charts: DemoChart[] };
export function RDemoGallery() {
  const [opened, setOpened] = useState(false);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!opened) return;
    let active = true;
    fetch("/r-demo/manifest.json").then(async response => {
      if (!response.ok) throw new Error();
      const value: Manifest = await response.json();
      if (value.synthetic !== true || !Array.isArray(value.charts) || !value.charts.length || value.charts.some(chart => !/^[a-z_]+$/.test(chart.key) || typeof chart.label !== "string")) throw new Error();
      if (active) { setManifest(value); setError(""); }
    }).catch(() => { if (active) setError("演示图片尚未准备好，请运行 r_viz/prepare_demo_gallery.py 后重试。"); });
    return () => { active = false; };
  }, [opened]);
  const chart = manifest?.charts[selected];
  return <section className="panel source-record" aria-label="合成演示图库" style={{ marginBottom: "1.5rem" }}>
    <p className="page-kicker">SYNTHETIC DEMO · NOT EXPERIMENTAL EVIDENCE</p>
    <h3 className="section-title-sm">R 图表演示图库</h3>
    <p className="section-help">14 种图表配套独立 key 数据。全部为合成演示，不代表真实实验、数据库互作或富集结论，不写入正式分析任务。</p>
    <button type="button" className="btn btn-secondary" aria-expanded={opened} onClick={() => setOpened(!opened)}>{opened ? "收起演示图库" : "查看全部图表与 key 数据"}</button>
    {opened && <>
      {error && <p className="notice-error" role="alert">{error}</p>}
      {!manifest && !error && <p role="status">正在读取演示图片…</p>}
      {manifest && chart && <>
        <p className="notice-warning">{manifest.disclaimer}</p>
        <label className="field-label" htmlFor="r-demo-selection">选择演示图表（共 {manifest.charts.length} 种）</label>
        <select id="r-demo-selection" className="input" value={selected} onChange={event => setSelected(Number(event.target.value))}>
          {manifest.charts.map((item, index) => <option key={item.key} value={index}>{item.label}</option>)}
        </select>
        <p className="section-help">图表 key：{chart.key} · {chart.rendererVersion} · 合成演示专用</p>
        <img className="visualization-preview" src={`/r-demo/${chart.key}.svg`} alt={`合成演示（非真实实验）：${chart.label}`} />
        <div className="source-record-actions">{["json", "svg", "png", "pdf", "html"].map(format => <a className="btn btn-secondary" key={format} download href={`/r-demo/${chart.key}.${format}`}>{format === "json" ? "下载 key 数据 JSON" : `下载 ${format.toUpperCase()}`}</a>)}</div>
      </>}
    </>}
  </section>;
}
