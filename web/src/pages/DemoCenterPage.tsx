import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { RDemoGallery } from "../components/RDemoGallery";

export function DemoCenterPage() {
  return <main className="site-home demo-center" id="main-content">
    <a className="skip-link" href="#demo-content">跳到图库内容</a>
    <header className="site-nav"><Link className="site-brand" to="/">远志 AI Scientist</Link><nav aria-label="图库导航"><Link to="/">返回首页</Link><Link to="/proteomics">蛋白组学分析</Link><Link to="/research">药理检索</Link></nav></header>
    <div className="demo-content" id="demo-content">
      <div className="page-heading"><div className="page-heading-copy"><h1 className="page-title">演示图库</h1><p className="page-description">浏览图表，打开交互窗口或下载图表与配套数据。</p></div><Link className="btn btn-secondary" to="/"><ArrowLeft size={16} />返回首页</Link></div>
      <RDemoGallery defaultOpen embedded />
    </div>
  </main>;
}
