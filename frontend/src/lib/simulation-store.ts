"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

export type SpeedOption = "1" | "6" | "24";
export type SimBounds = { start: number; end: number };

export const MINUTE_MS = 60 * 1000;
export const DEFAULT_SIM_BOUNDS: SimBounds = {
  start: new Date(2017, 9, 1, 0, 0, 0).getTime(),
  end: new Date(2017, 11, 31, 23, 0, 0).getTime(),
};

export const SPEED_OPTIONS: Array<{ value: SpeedOption; label: string }> = [
  { value: "1", label: "1h/s" },
  { value: "6", label: "6h/s" },
  { value: "24", label: "24h/s" },
];

type SimulationState = {
  simNow: number | null;
  isPlaying: boolean;
  speed: SpeedOption;
  bounds: SimBounds | null;
};

type Subscriber = () => void;
type Unsubscribe = () => void;

const DEFAULT_STATE: SimulationState = {
  simNow: DEFAULT_SIM_BOUNDS.start,
  isPlaying: false,
  speed: "6",
  bounds: DEFAULT_SIM_BOUNDS,
};

let state: SimulationState = { ...DEFAULT_STATE };
const subscribers = new Set<Subscriber>();

function subscribe(cb: Subscriber): Unsubscribe {
  subscribers.add(cb);
  return () => {
    subscribers.delete(cb);
  };
}

function getSnapshot(): SimulationState {
  return state;
}

function write(patch: Partial<SimulationState>) {
  state = { ...state, ...patch };
  subscribers.forEach((fn) => fn());
}

function clampToBounds(value: number, bounds: SimBounds) {
  return Math.max(bounds.start, Math.min(bounds.end, value));
}

export function setSimNow(ts: number | null) {
  write({ simNow: ts });
}

export function setIsPlaying(flag: boolean | ((current: boolean) => boolean)) {
  write({ isPlaying: typeof flag === "function" ? flag(state.isPlaying) : flag });
}

export function setSpeed(speed: SpeedOption) {
  write({ speed });
}

export function setBounds(bounds: SimBounds | null) {
  if (!bounds) {
    write({ bounds: DEFAULT_SIM_BOUNDS, simNow: DEFAULT_SIM_BOUNDS.start, isPlaying: false });
    return;
  }

  const nextNow =
    state.simNow == null || state.simNow < bounds.start || state.simNow > bounds.end
      ? bounds.start
      : clampToBounds(state.simNow, bounds);

  write({ bounds, simNow: nextNow, isPlaying: false });
}

export function tickSimNow(hourMs: number, tickMs: number) {
  const { bounds, simNow, speed } = state;
  if (!bounds || simNow == null || bounds.end <= bounds.start) return;

  const next = Math.min(simNow + Number(speed) * hourMs * (tickMs / 1000), bounds.end);
  write({ simNow: next, isPlaying: next >= bounds.end ? false : state.isPlaying });
}

export function useSimulationStore() {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const playToggle = useCallback(() => {
    const { bounds, simNow } = getSnapshot();
    if (!bounds || simNow == null || bounds.end <= bounds.start) return;
    if (simNow >= bounds.end) {
      write({ simNow: bounds.start, isPlaying: true });
      return;
    }
    setIsPlaying((current) => !current);
  }, []);

  const scrub = useCallback((value: number) => {
    const { bounds } = getSnapshot();
    if (!bounds) return;
    write({ simNow: clampToBounds(value, bounds), isPlaying: false });
  }, []);

  const reset = useCallback(() => {
    const { bounds } = getSnapshot();
    if (!bounds) return;
    write({ simNow: bounds.start, isPlaying: false });
  }, []);

  return useMemo(
    () => ({
      ...snapshot,
      playToggle,
      scrub,
      reset,
      setSpeed,
    }),
    [snapshot, playToggle, scrub, reset],
  );
}
