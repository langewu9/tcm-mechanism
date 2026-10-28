import { useId, useRef, useState } from "react";

export function HeroScroll() {
  const [isCycling, setIsCycling] = useState(false);
  const cycleRunning = useRef(false);
  const [assetsReady, setAssetsReady] = useState({ roller: false, paper: false });
  const paperId = useId();
  const isReady = assetsReady.roller && assetsReady.paper;

  const replayScroll = () => {
    // Complete one continuous gesture; crossing the edge again must not restart it.
    if (!isReady || cycleRunning.current) return;
    cycleRunning.current = true;
    setIsCycling(true);
  };

  return (
    <div
      className={`hero-scroll-art${isCycling ? " is-cycling" : ""}`}
      aria-label="远志卷轴，悬停、轻触或按回车，收起后重新展开"
      role="button"
      tabIndex={0}
      aria-disabled={!isReady || isCycling}
      aria-controls={paperId}
      onPointerEnter={event => { if (event.pointerType !== "touch") replayScroll(); }}
      onPointerUp={event => { if (event.pointerType === "touch") replayScroll(); }}
      onClick={replayScroll}
      onKeyDown={event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          replayScroll();
        }
      }}
    >
      <div className="hero-scroll-stage" onAnimationEnd={event => {
        if (event.target === event.currentTarget && event.animationName === "yz-scroll-recoil") {
          cycleRunning.current = false;
          setIsCycling(false);
        }
      }}>
        <img
          src="/images/yuanzhi-scroll/top-roller.png"
          alt=""
          width={896}
          height={112}
          fetchPriority="high"
          decoding="async"
          className="hero-scroll-roller hero-scroll-roller-top"
          onLoad={() => setAssetsReady(value => ({ ...value, roller: true }))}
          onError={() => setAssetsReady(value => ({ ...value, roller: true }))}
        />

        <div id={paperId} className="hero-scroll-paper-window">
          <div className="hero-scroll-paper">
            <img
              src="/images/yuanzhi-scroll/paper.png"
              alt=""
              fetchPriority="high"
              decoding="async"
              style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
              className="hero-scroll-paper-texture"
              onLoad={() => setAssetsReady(value => ({ ...value, paper: true }))}
              onError={() => setAssetsReady(value => ({ ...value, paper: true }))}
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
