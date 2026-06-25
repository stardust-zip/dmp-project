"use client";

import { Select } from "@/components/common/primitives";
import { Icon } from "@/components/common/icons";
import { clock } from "@/lib/format";
import { MINUTE_MS, SPEED_OPTIONS, type SimBounds, type SpeedOption } from "@/lib/simulation-store";

export { MINUTE_MS, SPEED_OPTIONS, type SimBounds, type SpeedOption };

export function SimulationControls({
  bounds,
  simNow,
  isPlaying,
  speed,
  disabled,
  onPlayToggle,
  onReset,
  onScrub,
  onSpeedChange,
}: {
  bounds: SimBounds | null;
  simNow: number | null;
  isPlaying: boolean;
  speed: SpeedOption;
  disabled: boolean;
  onPlayToggle: () => void;
  onReset: () => void;
  onScrub: (value: number) => void;
  onSpeedChange: (value: SpeedOption) => void;
}) {
  const canPlay = !!bounds && simNow != null && bounds.end > bounds.start && !disabled;
  const progress =
    bounds && simNow != null && bounds.end > bounds.start
      ? ((simNow - bounds.start) / (bounds.end - bounds.start)) * 100
      : 0;

  return (
    <div className="simulator-panel">
      <div className="simulator-controls">
        <button className="btn btn-sm btn-primary" type="button" disabled={!canPlay} onClick={onPlayToggle}>
          <Icon name={isPlaying ? "pause" : "play"} />
          {isPlaying ? "Pause" : "Play"}
        </button>
        <button className="btn btn-sm" type="button" disabled={!canPlay} onClick={onReset}>
          <Icon name="refresh" />
          Reset
        </button>
        <div className="simulator-speed">
          <Select value={speed} onChange={onSpeedChange} disabled={!canPlay} options={SPEED_OPTIONS} />
        </div>
      </div>
      <div className="simulator-readout">
        <span className="tag-cap">Simulated time</span>
        <b className="mono">{simNow == null ? "-" : clock(simNow)}</b>
        <span className="mono muted">{Math.max(0, Math.min(100, progress)).toFixed(0)}%</span>
      </div>
      <input
        className="simulator-slider"
        type="range"
        disabled={!canPlay}
        min={bounds?.start ?? 0}
        max={bounds?.end ?? 0}
        step={MINUTE_MS}
        value={simNow ?? bounds?.start ?? 0}
        onChange={(event) => onScrub(Number(event.target.value))}
        aria-label="Simulated time"
      />
    </div>
  );
}
