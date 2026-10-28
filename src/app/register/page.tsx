import Link from "next/link";
import { ArrowLeft, FileSearch, FlaskConical, Table2 } from "lucide-react";
import { AuthForm } from "@/components/AuthForm";

export default function RegisterPage() {
  return (
    <main className="auth-page">
      <section className="auth-context">
        <Link href="/" className="auth-back"><ArrowLeft size={16} /> 返回首页</Link>
        <div className="auth-context-copy">
          <span className="brand-seal" aria-hidden="true">岐</span>
          <p>Start a research workspace</p>
          <h2>从一个查询词开始，整理完整的研究证据链。</h2>
          <div className="auth-points">
            <span><FileSearch size={18} /> 中文疾病与中药检索</span>
            <span><FlaskConical size={18} /> 医案到靶点通路分析</span>
            <span><Table2 size={18} /> 原始结果与报告导出</span>
          </div>
        </div>
      </section>
      <div className="auth-form-pane">
        <AuthForm mode="register" />
        <p className="auth-switch">已有账号？<Link suppressHydrationWarning href="/login">登录工作台</Link></p>
      </div>
    </main>
  );
}
