import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { updateDataSourceSettings, type AdminDataSource } from "../api/sources";

export function SourceSettingsForm({ source, onSaved }: {
  source: AdminDataSource; onSaved: (source: AdminDataSource) => void;
}) {
  const [enabled, setEnabled] = useState(source.enabled);
  const [interval, setInterval] = useState(String(source.refresh_interval_hours ?? ""));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    pending.current = true;
    setSaving(true); setMessage(null); setError(null);
    try {
      const result = await updateDataSourceSettings(source.id, {
        enabled, refresh_interval_hours: interval === "" ? null : Number(interval),
      });
      if (!mounted.current) return;
      onSaved(result);
      setMessage("配置已保存。定时预览仍受部署开关和调度服务控制，入库需人工审核。");
    } catch (cause) {
      if (mounted.current) setError(cause instanceof ApiError ? cause.message : "保存失败，请稍后重试。");
    } finally {
      pending.current = false;
      if (mounted.current) setSaving(false);
    }
  }

  return <details className="source-settings">
    <summary>刷新计划与启停设置</summary>
    <form onSubmit={(event) => void save(event)} className="source-settings-form">
      <label><input type="checkbox" checked={enabled} disabled={saving}
        onChange={(event) => setEnabled(event.target.checked)} />启用此数据源</label>
      <label>刷新间隔（小时；留空仅手动）<input type="number" min={1} max={8760} step={1}
        value={interval} disabled={saving} onChange={(event) => setInterval(event.target.value)} /></label>
      <button type="submit" className="btn btn-secondary" disabled={saving}>{saving ? "保存中…" : "保存配置"}</button>
      <p className="section-help">停用不会删除已入库的数据或同步历史，也不会撤销已经执行的写入。</p>
      {message && <p role="status" className="notice-success">{message}</p>}
      {error && <p role="alert" className="notice-error">{error}</p>}
    </form>
  </details>;
}
