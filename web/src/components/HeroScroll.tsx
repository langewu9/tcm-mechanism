import { useEffect, useState } from "react";

export function HeroScroll() {
  const [isOpen, setIsOpen] = useState(false);
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => setIsOpen(true));
    return () => window.cancelAnimationFrame(frame);
  }, []);

  return (
    <div className={`hero-scroll-art${isOpen ? " is-open" : ""}`} aria-label="远志中医药理研究档案卷轴" aria-expanded={isOpen}>
      <div className="hero-scroll-stage">
        <span aria-hidden="true" className="hero-scroll-roller hero-scroll-roller-top" />
        <div className="hero-scroll-paper-window" aria-hidden={!isOpen}>
          <div className="hero-scroll-paper">
            <span aria-hidden="true" className="hero-scroll-paper-texture" />
            <svg className="hero-scroll-herb" viewBox="0 0 180 280" fill="none" aria-hidden="true">
              <path d="M18 258C70 203 78 132 145 27M62 190C29 180 18 151 26 129C50 129 72 147 74 174M80 145C48 134 43 108 50 87C75 88 91 104 91 129M103 106C79 88 81 64 91 47C114 54 125 72 117 95M56 213C80 215 98 232 99 253M133 53C142 34 158 24 172 26C170 46 159 59 139 63" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="hero-scroll-gold-node" aria-hidden="true" />
            <strong className="hero-scroll-title">远志</strong>
            <span className="hero-scroll-caption">求本远志<br />智药存档</span>
          </div>
        </div>
        <span aria-hidden="true" className="hero-scroll-roller hero-scroll-roller-bottom" />
      </div>
    </div>
  );
}
