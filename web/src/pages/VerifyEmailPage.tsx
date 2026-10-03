import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { resendVerificationEmail, verifyEmail, type EmailVerificationResult } from "../api/auth";
import { ApiError } from "../api/client";

function errorMessage(error: unknown) {
  if (!(error instanceof ApiError)) return "请求未完成，请稍后重试。";
  if (error.details && typeof error.details === "object" && !Array.isArray(error.details)) {
    const tokenDetail = (error.details as Record<string, unknown>).token;
    if (Array.isArray(tokenDetail) && typeof tokenDetail[0] === "string") return tokenDetail[0];
  }
  return error.message;
}

export function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [email, setEmail] = useState("");
  const [verification, setVerification] = useState<EmailVerificationResult | null>(null);
  const [resendNotice, setResendNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setVerification(await verifyEmail(token));
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function resend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setResendNotice(null);
    try {
      const response = await resendVerificationEmail(email);
      setResendNotice(response.message);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <main className="site-home auth-page"><section className="auth-card panel">
    <Link className="auth-back" to="/">← 返回首页</Link>
    <p className="page-kicker">Researcher account</p>
    <h1 className="page-title">验证研究者邮箱</h1>
    {verification ? <div className="notice-success" role="status"><strong>{verification.status === "verified" ? "邮箱已验证" : "邮箱已完成验证"}</strong><br />{verification.message}</div> : token ? <>
      <p className="page-description">点击下方确认按钮完成邮箱验证。为避免邮件安全扫描器提前使用链接，打开此页面不会自动验证。</p>
      {error && <div className="notice-error" role="alert">{error}</div>}
      <form className="auth-form" onSubmit={(event) => void confirm(event)}>
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "正在验证…" : "确认邮箱地址"}</button>
      </form>
    </> : <p className="page-description">输入账号申请时使用的邮箱，平台会在该邮箱仍有待验证申请时发送新链接。</p>}
    {resendNotice && <div className="notice-success" role="status">{resendNotice}</div>}
    {error && (!token || verification) && <div className="notice-error" role="alert">{error}</div>}
    {!verification && <form className="auth-form" onSubmit={(event) => void resend(event)}>
      <label className="form-label" htmlFor="verification-email">邮箱地址</label>
      <input className="field" id="verification-email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={254} required />
      <button className="btn btn-secondary" type="submit" disabled={busy}>{busy ? "正在发送…" : "重新发送验证邮件"}</button>
    </form>}
    <p className="auth-note">邮箱验证后仍需平台管理员启用账号。<Link to="/login">前往登录</Link></p>
  </section></main>;
}
