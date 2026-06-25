"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/common/icons";
import { SimulationControls } from "@/components/common/simulation-controls";
import { tickSimNow, useSimulationStore } from "@/lib/simulation-store";
import { clock } from "@/lib/format";

const HOUR_MS = 60 * 60 * 1000;
const TICK_MS = 250;

export function SimTopbarWidget() {
  const { bounds, simNow, isPlaying, speed, playToggle, reset, scrub, setSpeed } = useSimulationStore();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const canPlay = !!bounds && simNow != null && bounds.end > bounds.start;

  useEffect(() => {
    if (!isPlaying || !bounds || bounds.end <= bounds.start) return;
    const interval = window.setInterval(() => tickSimNow(HOUR_MS, TICK_MS), TICK_MS);
    return () => window.clearInterval(interval);
  }, [isPlaying, bounds]);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (rootRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    };
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [open]);

  return (
    <div className="topbar-sim" ref={rootRef}>
      <button className="icon-btn" type="button" disabled={!canPlay} onClick={playToggle} title={isPlaying ? "Pause simulation" : "Play simulation"}>
        <Icon name={isPlaying ? "pause" : "play"} />
      </button>
      <button
        className={`topbar-sim-clock${open ? " open" : ""}`}
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="tag-cap">Sim</span>
        <b className="mono">{simNow == null ? "-" : clock(simNow)}</b>
        <Icon name="chevDown" />
      </button>
      {open && (
        <div className="topbar-sim-popover">
          <SimulationControls
            bounds={bounds}
            simNow={simNow}
            isPlaying={isPlaying}
            speed={speed}
            disabled={!canPlay}
            onPlayToggle={playToggle}
            onReset={reset}
            onScrub={scrub}
            onSpeedChange={setSpeed}
          />
        </div>
      )}
    </div>
  );
}
