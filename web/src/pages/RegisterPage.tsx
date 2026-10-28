import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { registerResearcher, type RegistrationResult } from "../api/auth";

function validationMessage(details: unknown, field: string): string | null {
  if (!details || typeof details !== "object" || Array.isArray(details)) return null;
  const value = (details as Record<string, unknown>)[field];
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string").join(" ") || null;
  return null;
}

export function RegisterPage() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState<RegistrationResult | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setFieldErrors({});
    setBusy(true);
    const form = new FormData(event.currentTarget);
    try {
      const response = await registerResearcher(
        String(form.get("username") ?? ""),
        String(form.get("email") ?? ""),
        String(form.get("password") ?? ""),
        String(form.get("password_confirmation") ?? ""),
      );
      setResult(response);
    } catch (cause) {
      if (cause instanceof ApiError) {
        const errors = Object.fromEntries(
          ["username", "email", "password", "password_confirmation"].flatMap((field) => {
            const message = validationMessage(cause.details, field);
            return message ? [[field, message]] : [];
          }),
        );
        setFieldErrors(errors);
        setError(Object.keys(errors).length ? "请检查并修正表单中的信息。" : cause.message);
      } else {
        setError("注册申请提交失败，请稍后重试。");
      }
    } finally {
      setBusy(false);
    }
  }

  return <main className="site-home auth-page"><section className="auth-card panel">
    <Link className="auth-back" to="/">← 返回首页</Link><h1 className="page-title">申请研究者账号</h1>
    {result ? <>
      <div className="notice-success" role="status"><strong>申请已提交</strong><br />{result.message}</div>
      <p className="page-description">请先点击邮件中的验证链接，再等待平台管理员审核启用账号。邮箱验证不会自动开通研究权限。</p>
      <Link className="btn btn-primary" to="/verify-email">重新发送验证邮件</Link>
    </> : <>
      <p className="page-description">提交申请后需验证邮箱，并经管理员审核。</p>
      {error && <div className="notice-error" role="alert">{error}</div>}
      <form className="auth-form" onSubmit={submit}>
        <label className="form-label" htmlFor="register-username">用户名</label>
        <input className="field" id="register-username" name="username" autoComplete="username" maxLength={150} required aria-describedby={fieldErrors.username ? "register-username-error" : undefined} />
        {fieldErrors.username && <small className="form-field-error" id="register-username-error">{fieldErrors.username}</small>}
        <label className="form-label" htmlFor="register-email">邮箱</label>
        <input className="field" id="register-email" name="email" type="email" autoComplete="email" maxLength={254} required aria-describedby={fieldErrors.email ? "register-email-error" : undefined} />
        {fieldErrors.email && <small className="form-field-error" id="register-email-error">{fieldErrors.email}</small>}
        <small className="auth-note">用于接收验证邮件。</small>
        <label className="form-label" htmlFor="register-password">密码</label>
        <input className="field" id="register-password" name="password" type="password" autoComplete="new-password" minLength={8} required aria-describedby={fieldErrors.password ? "register-password-error" : "register-password-help"} />
        {fieldErrors.password ? <small className="form-field-error" id="register-password-error">{fieldErrors.password}</small> : <small className="auth-note" id="register-password-help">请避免使用常见密码、用户名或邮箱信息。</small>}
        <label className="form-label" htmlFor="register-password-confirmation">确认密码</label>
        <input className="field" id="register-password-confirmation" name="password_confirmation" type="password" autoComplete="new-password" required aria-describedby={fieldErrors.password_confirmation ? "register-password-confirmation-error" : undefined} />
        {fieldErrors.password_confirmation && <small className="form-field-error" id="register-password-confirmation-error">{fieldErrors.password_confirmation}</small>}
        <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "正在提交…" : "提交账号申请"}</button>
      </form>
    </>}
    <p className="auth-note">已有账号？<Link to="/login">前往登录</Link></p>
  </section></main>;
}
