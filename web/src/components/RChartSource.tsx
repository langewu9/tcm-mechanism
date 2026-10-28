import { createContext, useContext, type ReactNode } from "react";
import { SubviewTabs } from "./SubviewTabs";
import { RDemoGallery } from "./RDemoGallery";
import { RPublicGallery } from "./RPublicGallery";

type ChartSourceSelection = { source: string; onChange: (source: string) => void };
const ChartSourceContext = createContext<ChartSourceSelection | null>(null);

/** The gallery owns the selection so chart subpage remounts cannot reset it. */
export function RChartSourceProvider({ source, onChange, children }: ChartSourceSelection & { children: ReactNode }) {
  return <ChartSourceContext.Provider value={{ source, onChange }}>{children}</ChartSourceContext.Provider>;
}

export function RChartSource({ chartKey, children }: { chartKey: string; children: ReactNode }) {
  const selection = useContext(ChartSourceContext);
  if (!selection) throw new Error("RChartSource requires a gallery source selection provider.");
  return <SubviewTabs label="图表数据来源" value={selection.source} onChange={selection.onChange} views={[
    { key: "task", label: "当前任务图表", content: children },
    { key: "demo", label: "合成演示图表", content: <RDemoGallery chartKey={chartKey} defaultOpen embedded /> },
    { key: "public", label: "公开数据示例", content: <RPublicGallery chartKey={chartKey} /> },
  ]} />;
}
