import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { lazy, Suspense } from "react";
import { PageLoadBoundary, PageLoading } from "./PageLoadBoundary";
import { HomePage } from "../pages/HomePage";
import { LoginPage } from "../pages/LoginPage";
import { RegisterPage } from "../pages/RegisterPage";
import { VerifyEmailPage } from "../pages/VerifyEmailPage";
import { RequireAuth } from "./RequireAuth";
import { WorkspaceLayout } from "../components/AppShell";
const CasesPage = lazy(() => import("../pages/CaseLibraryPage").then((module) => ({ default: module.CaseLibraryPage })));
const DatasetsPage = lazy(() => import("../pages/DatasetsPage").then((module) => ({ default: module.DatasetsPage })));
const ProteomicsPage = lazy(() => import("../pages/ProteomicsPage").then((module) => ({ default: module.ProteomicsPage })));
const SourcesPage = lazy(() => import("../pages/SourcesPage").then((module) => ({ default: module.SourcesPage })));
const NetworkPharmacologyPage = lazy(() => import("../pages/NetworkPharmacologyPage").then((module) => ({ default: module.NetworkPharmacologyPage })));
const KnowledgeExplorerPage = lazy(() => import("../pages/KnowledgeExplorerPage").then((module) => ({ default: module.KnowledgeExplorerPage })));
const ResearchAssistantPage = lazy(() => import("../pages/ResearchAssistantPage").then((module) => ({ default: module.ResearchAssistantPage })));
const DashboardPage = lazy(() => import("../pages/DashboardPage").then((module) => ({ default: module.DashboardPage })));
const AdminOverviewPage = lazy(() => import("../pages/AdminOverviewPage").then((module) => ({ default: module.AdminOverviewPage })));
const AnalysisPage = lazy(() => import("../pages/AnalysisPage").then((module) => ({ default: module.AnalysisPage })));
const DemoCenterPage = lazy(() => import("../pages/DemoCenterPage").then((module) => ({ default: module.DemoCenterPage })));
const TaskHistoryPage = lazy(() => import("../pages/TaskHistoryPage").then((module) => ({ default: module.TaskHistoryPage })));
export function App() {
  return <BrowserRouter><PageLoadBoundary><Suspense fallback={<PageLoading />}><Routes>
    <Route path="/" element={<HomePage />} />
    <Route path="/login" element={<LoginPage />} />
    <Route path="/register" element={<RegisterPage />} />
    <Route path="/verify-email" element={<VerifyEmailPage />} />
    <Route path="/demo" element={<DemoCenterPage />} />
    <Route element={<RequireAuth />}><Route element={<WorkspaceLayout />}>
      <Route path="/dashboard" element={<DashboardPage />} />
      <Route path="/cases" element={<CasesPage />} />
      <Route path="/datasets" element={<DatasetsPage />} />
      <Route path="/proteomics" element={<ProteomicsPage />} />
      <Route path="/network-pharmacology" element={<NetworkPharmacologyPage />} />
      <Route path="/visualization" element={<NetworkPharmacologyPage />} />
      <Route path="/research" element={<KnowledgeExplorerPage />} />
      <Route path="/assistant" element={<ResearchAssistantPage />} />
      <Route path="/analysis" element={<AnalysisPage />} />
      <Route path="/tasks/:taskId" element={<TaskHistoryPage />} />
      <Route path="/admin" element={<AdminOverviewPage />} />
      <Route path="/admin/sources" element={<SourcesPage />} />
      <Route path="/admin/integrations" element={<Navigate to="/dashboard" replace />} />
      <Route path="/api-integration" element={<Navigate to="/dashboard" replace />} />
    </Route></Route>
    <Route path="*" element={<main className="site-home"><section className="empty-state"><strong>页面不存在</strong><p>请检查访问地址，或返回平台首页。</p><a className="btn btn-secondary" href="/">返回首页</a></section></main>} />
  </Routes></Suspense></PageLoadBoundary></BrowserRouter>;
}
