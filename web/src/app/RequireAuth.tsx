import { useEffect, useState } from "react";
import { Link, Navigate, Outlet } from "react-router-dom";
import { getSession, type Session } from "../api/auth";
import { ApiError } from "../api/client";

export function RequireAuth() {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setError(null);
    getSession()
      .then((value) => { if (active) setSession(value); })
      .catch((cause: unknown) => {
        if (!active) return;
        setError(cause instanceof ApiError ? cause.message : "无法检查登录状态，请稍后重试。");
      });
    return () => { active = false; };
  }, [attempt]);

  if (error) return <main className="workspace-page"><section className="panel empty-state" role="alert">
    <strong>暂时无法打开研究工作区</strong><p>{error}</p>
    <div className="workspace-actions"><button className="btn btn-primary" onClick={() => setAttempt((value) => value + 1)}>重试</button><Link className="btn btn-secondary" to="/">返回首页</Link></div>
  </section></main>;
  if (!session) return <main className="workspace-page"><p className="workspace-loading" role="status">正在确认登录状态…</p></main>;
  if (!session.authenticated) return <Navigate to="/login" replace />;
  return <Outlet context={session.user} />;
}
