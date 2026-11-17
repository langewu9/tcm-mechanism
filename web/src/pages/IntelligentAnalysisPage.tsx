import { useSearchParams } from "react-router-dom";
import { SubviewTabs } from "../components/SubviewTabs";
import { CaseVisualizationWorkspace } from "../components/CaseVisualizationWorkspace";
import { AnalysisPage } from "./AnalysisPage";
import "../styles/intelligent-analysis.css";

export function IntelligentAnalysisPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const explicitView = searchParams.get("analysisView");
  const view = explicitView === "cases" ? "cases" : explicitView === "text" || searchParams.has("textTask") ? "text" : "cases";

  function changeView(nextView: string) {
    setSearchParams(previous => {
      const next = new URLSearchParams(previous);
      next.set("analysisView", nextView);
      return next;
    });
  }

  return <section className={`intelligent-analysis-page${view === "cases" ? " intelligent-analysis-page--cases" : ""}`}>
    <SubviewTabs label="智能分析类型" value={view} onChange={changeView} keepMounted={false} views={[
      { key: "cases", label: "医案可视化", content: <CaseVisualizationWorkspace /> },
      { key: "text", label: "证候与网络药理分析", content: <AnalysisPage /> },
    ]} />
  </section>;
}
