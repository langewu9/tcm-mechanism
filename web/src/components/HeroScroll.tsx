import { useEffect, useState } from "react";

export function HeroScroll() {
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => setIsOpen(true));
    return () => window.cancelAnimationFrame(frame);
  }, []);

  return (
    <div
      className={`hero-scroll-art${isOpen ? " is-open" : ""}`}
      aria-label="远志中医药理研究档案卷轴"
      aria-expanded={isOpen}
    >
      <div className="hero-scroll-stage">
        <img
          src="/images/yuanzhi-scroll/top-roller.png"
          alt=""
          width={896}
          height={112}
          fetchPriority="high"
          decoding="async"
          className="hero-scroll-roller hero-scroll-roller-top"
        />

        <div className="hero-scroll-paper-window" aria-hidden={!isOpen}>
          <div className="hero-scroll-paper">
            <img
              src="/images/yuanzhi-scroll/paper.png"
              alt=""
              fetchPriority="high"
              decoding="async"
              style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
              className="hero-scroll-paper-texture"
            />
            <img
              src="/images/yuanzhi-scroll/herb-lineart.png"
              alt=""
              width={176}
              height={280}
              decoding="async"
              className="hero-scroll-herb"
            />
            <span className="hero-scroll-gold-node" aria-hidden="true" />
            <strong className="hero-scroll-title">远志</strong>
            <span className="hero-scroll-caption">求本远志<br />智药存档</span>
          </div>
        </div>

        <img
          src="/images/yuanzhi-scroll/top-roller.png"
          alt=""
          width={896}
          height={112}
          decoding="async"
          className="hero-scroll-roller hero-scroll-roller-bottom"
        />
      </div>
    </div>
  );
}
