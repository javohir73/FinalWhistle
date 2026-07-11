"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/** Reveals children with a fade-up the first time they scroll into view. */
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }

    // Content that's already on screen the moment this mounts — e.g. the top
    // of a tab panel that just swapped in client-side, not a fresh page load
    // — must show immediately. Waiting on the observer's first callback (an
    // async "queue an IntersectionObserverEntry" step) left it stuck at
    // opacity:0 until some later scroll/resize forced a recompute, which is
    // what made the AI bracket's Round-of-16 render blank on load. Below-fold
    // rounds still get the real scroll-triggered reveal via the observer.
    const rect = el.getBoundingClientRect();
    if (rect.top < window.innerHeight && rect.bottom > 0) {
      setVisible(true);
      return;
    }

    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          io.disconnect();
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={cn("reveal", visible && "is-visible", className)}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}
