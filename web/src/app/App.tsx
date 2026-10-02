import { BrowserRouter, Route, Routes } from "react-router-dom";
import { HomePage } from "../pages/HomePage";
import { LoginPage } from "../pages/LoginPage";
import { RegisterPage } from "../pages/RegisterPage";
export function App() {
  return <BrowserRouter><Routes>
    <Route path="/" element={<HomePage />} />
    <Route path="/login" element={<LoginPage />} />
    <Route path="/register" element={<RegisterPage />} />
    <Route path="*" element={<main className="site-home"><section className="empty-state"><strong>页面尚未接入</strong><p>这个模块会在对应业务源码确认后补齐。</p><a className="btn btn-secondary" href="/">返回首页</a></section></main>} />
  </Routes></BrowserRouter>;
}
