import { useEffect, useRef, useState } from "react";
import { FlaskConical, Leaf, Network, Route } from "lucide-react";
const metricIcons = { herb: Leaf, compound: FlaskConical, target: Network, pathway: Route };
type HomeMetricProps = { label: string; value: number | null; kind: keyof typeof metricIcons };
export function HomeMetric({ label, value, kind }: HomeMetricProps) {
  const [displayValue, setDisplayValue] = useState(0);
  const [hasEntered, setHasEntered] = useState(false);
  const metricRef = useRef<HTMLDivElement>(null);
  const Icon = metricIcons[kind];
  useEffect(() => {
    if (!("IntersectionObserver" in window)) { setHasEntered(true); return; }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting && entry.intersectionRatio >= 0.6)) {
        setHasEntered(true);
        observer.disconnect();
      }
    }, { threshold: 0.6 });
    if (metricRef.current) observer.observe(metricRef.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (value === null || !hasEntered) return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (motion.matches) { setDisplayValue(value); return; }
    const duration = 1800;
    const startedAt = performance.now();
    let frameId = 0;
    const tick = (now: number) => {
      const progress = Math.min((now - startedAt) / duration, 1);
      setDisplayValue(Math.round(value * (1 - Math.pow(1 - progress, 3))));
      if (progress < 1) frameId = requestAnimationFrame(tick);
    };
    const finish = () => {
      if (motion.matches) { cancelAnimationFrame(frameId); setDisplayValue(value); }
    };
    frameId = requestAnimationFrame(tick);
    motion.addEventListener("change", finish);
    return () => { cancelAnimationFrame(frameId); motion.removeEventListener("change", finish); };
  }, [value, hasEntered]);
  const text = value === null ? "—" : displayValue.toLocaleString("zh-CN");
  return <div className="hero-metric" ref={metricRef}><Icon size={19} aria-hidden="true" /><div><strong aria-label={`${label} ${value === null ? "暂无数据" : value.toLocaleString("zh-CN")}`}>{text}</strong><span>{label}</span></div></div>;
}
