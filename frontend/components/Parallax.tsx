"use client";

import { useEffect, useRef } from "react";

/** Moves its children as the element scrolls through the viewport.
 *  `speed` = px of vertical travel; `rotate` = deg of rotation across the range.
 *  Uses one rAF-throttled scroll listener and is disabled for reduced-motion. */
export function Parallax({
  children,
  speed = 40,
  rotate = 0,
  className,
}: {
  children: React.ReactNode;
  speed?: number;
  rotate?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    ) {
      return;
    }

    let raf = 0;
    const update = () => {
      raf = 0;
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight || 1;
      const progress = (r.top + r.height / 2 - vh / 2) / vh; // ~ -0.6..0.6
      el.style.transform = `translate3d(0, ${(-progress * speed).toFixed(1)}px, 0) rotate(${(progress * rotate).toFixed(2)}deg)`;
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [speed, rotate]);

  return (
    <div ref={ref} className={className} style={{ willChange: "transform" }}>
      {children}
    </div>
  );
}
