import { useEffect, useRef, useState } from "react";

export function ArtifactPreview({ src, alt }: { src: string; alt: string }) {
  const [state, setState] = useState({ src, attempt: 0, failed: false });
  const current = state.src === src ? state : { src, attempt: 0, failed: false };
  const binding = `${src}|${current.attempt}`;
  const active = useRef<string | null>(binding);
  active.current = binding;
  useEffect(() => {
    active.current = binding;
    return () => { active.current = null; };
  }, [binding]);
  if (current.failed) return <div className="notice-error" role="alert">
    <p>图表文件暂不可读取，可能缺失、损坏或服务暂不可用。分析记录仍保留；重新读取失败时，请联系管理员并提供任务编号。</p>
    <button className="btn btn-secondary" type="button" onClick={() => setState({ src, attempt: current.attempt + 1, failed: false })}>重新读取图表文件</button>
  </div>;
  const requestUrl = current.attempt ? `${src}${src.includes("?") ? "&" : "?"}readAttempt=${current.attempt}` : src;
  return <img className="visualization-preview" src={requestUrl} alt={alt} onError={() => {
    if (active.current === binding) setState({ src, attempt: current.attempt, failed: true });
  }} />;
}
