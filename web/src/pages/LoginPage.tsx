import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { login } from "../api/auth";
export function LoginPage() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(null); setBusy(true);
    const form = new FormData(event.currentTarget);
    try { await login(String(form.get("username") ?? ""), String(form.get("password") ?? "")); navigate("/cases", { replace: true }); }
    catch (cause) { setError(cause instanceof ApiError ? cause.message : "登录失败，请稍后重试。"); }
    finally { setBusy(false); }
  }
  return <main className="site-home auth-page"><section className="auth-card panel">
    <Link className="auth-back" to="/">← 返回首页</Link><p className="page-kicker">Researcher account</p><h1 className="page-title">登录研究平台</h1>
    <p className="page-description">使用平台分配的研究者账号登录。会话由 Django 服务端管理。</p>
    {error && <div className="notice-error" role="alert">{error}</div>}
    <form className="auth-form" onSubmit={submit}><label className="form-label" htmlFor="username">用户名</label><input className="field" id="username" name="username" autoComplete="username" required />
      <label className="form-label" htmlFor="password">密码</label><input className="field" id="password" name="password" type="password" autoComplete="current-password" required />
      <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "正在登录…" : "登录"}</button></form>
    <p className="auth-note">研究者账号注册暂未开放，请联系平台管理员创建账号。</p>
  </section></main>;
}
