import Link from "next/link";
import { ArrowLeft, Database, Network, ShieldCheck } from "lucide-react";
import { AuthForm } from "@/components/AuthForm";

export default function LoginPage() {
  return (
    <main className="auth-page">
      <section className="auth-context">
        <Link href="/" className="auth-back"><ArrowLeft size={16} /> 返回首页</Link>
        <div className="auth-context-copy">
          <span className="brand-seal" aria-hidden="true">岐</span>
          <p>Qihuang research workspace</p>
          <h2>让每一条药理证据都有出处，也有下一步。</h2>
          <div className="auth-points">
            <span><Database size={18} /> 本地数据库与动态同步</span>
            <span><Network size={18} /> 查询驱动网络药理图谱</span>
            <span><ShieldCheck size={18} /> 研究员与管理员权限隔离</span>
          </div>
        </div>
      </section>
      <div className="auth-form-pane">
        <AuthForm mode="login" />
        <p className="auth-switch">还没有账号？<Link suppressHydrationWarning href="/register">创建研究账号</Link></p>
      </div>
    </main>
  );
}
