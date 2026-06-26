"use client";

import { useRef, useCallback, useState } from "react";
import { HeroSection } from "@/components/hero-section";
import { App } from "@/components/app";

/**
 * Two-section vertical shell:
 *   section 0 → HeroSection  (full viewport height)
 *   section 1 → App          (full viewport height)
 *
 * Scrolling is snap-based (CSS scroll-snap). The hero "Enter" arrow
 * and any programmatic call to `scrollToApp` also works.
 */
export function AppShell() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [locked, setLocked] = useState(false);

  const scrollToApp = useCallback(() => {
    scrollRef.current?.scrollTo({
      top: window.innerHeight,
      behavior: "smooth",
    });
  }, []);

  const handleModeSelected = useCallback(() => {
    // Snap to app section first, then lock overflow so hero is unreachable
    scrollRef.current?.scrollTo({ top: window.innerHeight, behavior: "instant" });
    setLocked(true);
  }, []);

  return (
    <div
      ref={scrollRef}
      style={{
        width: "100vw",
        height: "100vh",
        overflowY: locked ? "hidden" : "scroll",
        scrollSnapType: locked ? "none" : "y mandatory",
        // Hide the scrollbar — navigation is intentional (arrow / wheel)
        scrollbarWidth: "none",
      }}
      // webkit scrollbar hide
      className="no-scrollbar"
    >
      {/* ── Section 1: Hero ── */}
      <div
        style={{
          width: "100%",
          height: "100vh",
          flexShrink: 0,
          scrollSnapAlign: "start",
          position: "relative",
          pointerEvents: locked ? "none" : undefined,
        }}
      >
        <HeroSection onEnter={scrollToApp} />
      </div>

      {/* ── Section 2: App ── */}
      <div
        style={{
          width: "100%",
          height: "100vh",
          flexShrink: 0,
          scrollSnapAlign: "start",
          position: "relative",
          overflow: "hidden",
        }}
      >
        <App onModeSelected={handleModeSelected} />
      </div>
    </div>
  );
}
