import { BrowserRouter, Route, Routes } from "react-router-dom";
import { HomePage } from "../pages/HomePage";
import { LoginPage } from "../pages/LoginPage";
import { RegisterPage } from "../pages/RegisterPage";
import { VerifyEmailPage } from "../pages/VerifyEmailPage";
import { CasesPage } from "../pages/CasesPage";
import { RequireAuth } from "./RequireAuth";
import { DatasetsPage } from "../pages/DatasetsPage";
import { ProteomicsPage } from "../pages/ProteomicsPage";
import { SourcesPage } from "../pages/SourcesPage";
import { NetworkPharmacologyPage } from "../pages/NetworkPharmacologyPage";
import { KnowledgeExplorerPage } from "../pages/KnowledgeExplorerPage";
import { ResearchAssistantPage } from "../pages/ResearchAssistantPage";
export function App() {
  return <BrowserRouter><Routes>
    <Route path="/" element={<HomePage />} />
    <Route path="/login" element={<LoginPage />} />
    <Route path="/register" element={<RegisterPage />} />
    <Route path="/verify-email" element={<VerifyEmailPage />} />
    <Route element={<RequireAuth />}><Route path="/cases" element={<CasesPage />} /><Route path="/datasets" element={<DatasetsPage />} /><Route path="/proteomics" element={<ProteomicsPage />} /><Route path="/network-pharmacology" element={<NetworkPharmacologyPage />} /><Route path="/research" element={<KnowledgeExplorerPage />} /><Route path="/assistant" element={<ResearchAssistantPage />} /><Route path="/admin/sources" element={<SourcesPage />} /></Route>
    <Route path="*" element={<main className="site-home"><section className="empty-state"><strong>页面尚未接入</strong><p>这个模块会在对应业务源码确认后补齐。</p><a className="btn btn-secondary" href="/">返回首页</a></section></main>} />
  </Routes></BrowserRouter>;
}
