import { useEffect, useState } from "react";
import { FlaskConical, Leaf, Network, Route } from "lucide-react";
const metricIcons = { herb: Leaf, compound: FlaskConical, target: Network, pathway: Route };
type HomeMetricProps = { label: string; value: number | null; kind: keyof typeof metricIcons };
export function HomeMetric({ label, value, kind }: HomeMetricProps) {
  const [displayValue, setDisplayValue] = useState(0); const Icon = metricIcons[kind];
  useEffect(() => {
    if (value === null) return;
    const duration = 1100; const startedAt = performance.now(); let frameId = 0;
    const tick = (now: number) => { const progress = Math.min((now - startedAt) / duration, 1); setDisplayValue(Math.round(value * (1 - Math.pow(1 - progress, 3)))); if (progress < 1) frameId = requestAnimationFrame(tick); };
    frameId = requestAnimationFrame(tick); return () => cancelAnimationFrame(frameId);
  }, [value]);
  const text = value === null ? "—" : displayValue.toLocaleString("zh-CN");
  return <div className="hero-metric"><Icon size={19} aria-hidden="true" /><div><strong aria-label={`${label} ${value === null ? "暂无数据" : value.toLocaleString("zh-CN")}`}>{text}</strong><span>{label}</span></div></div>;
}
