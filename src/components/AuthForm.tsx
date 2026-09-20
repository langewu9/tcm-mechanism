"use client";

import { LockKeyhole, LogIn, Mail, UserPlus, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(formData: FormData) {
    setLoading(true);
    setError("");
    const payload = Object.fromEntries(formData);
    const response = await fetch(`/api/auth/${mode}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    setLoading(false);
    if (!response.ok) {
      setError(data.error || "提交失败");
      return;
    }
    const next = new URLSearchParams(window.location.search).get("next");
    router.push(next || "/dashboard");
    router.refresh();
  }

  return (
    <form action={submit} className="auth-card" aria-label={mode === "login" ? "登录表单" : "注册表单"}>
      <div className="auth-card-heading">
        <p>{mode === "login" ? "Welcome back" : "Research account"}</p>
        <h1>{mode === "login" ? "登录研究工作台" : "创建研究账号"}</h1>
        <span>{mode === "login" ? "继续管理药理数据、医案和分析任务。" : "注册后即可使用检索、分析、可视化与导出功能。"}</span>
      </div>

      {mode === "register" ? (
        <label className="form-label" htmlFor="name">姓名
          <span className="field-with-icon"><UserRound size={17} /><input id="name" className="field" name="name" autoComplete="name" placeholder="请输入姓名" required /></span>
        </label>
      ) : null}
      <label className="form-label" htmlFor="email">邮箱
        <span className="field-with-icon"><Mail size={17} /><input id="email" className="field" name="email" type="email" autoComplete="email" placeholder="name@example.com" required /></span>
      </label>
      <label className="form-label" htmlFor="password">密码
        <span className="field-with-icon"><LockKeyhole size={17} /><input id="password" className="field" name="password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} placeholder="至少 8 位" minLength={8} required /></span>
      </label>
      {error ? <p className="notice-error" role="alert" aria-live="polite">{error}</p> : null}
      <button className="btn btn-primary w-full" disabled={loading}>
        {mode === "login" ? <LogIn size={17} /> : <UserPlus size={17} />}
        {loading ? "处理中..." : mode === "login" ? "登录" : "注册"}
      </button>
      <p className="auth-privacy">账号信息仅用于本地研究工作区，不会写入外部服务。</p>
    </form>
  );
}
