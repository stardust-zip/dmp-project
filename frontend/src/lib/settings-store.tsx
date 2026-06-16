"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";

export type Theme = "light" | "dark";
export type Accent = "blue" | "indigo" | "teal" | "slate";
export type Density = "compact" | "comfortable";

export interface Settings {
  theme: Theme;
  accent: Accent;
  density: Density;
}

type Subscriber = () => void;
type Unsubscribe = () => void;

const ACCENTS_LIGHT: Record<Accent, Record<string, string>> = {
  blue: { "--accent": "#2563eb", "--accent-600": "#2563eb", "--accent-700": "#1d4ed8", "--accent-soft": "#eff6ff", "--accent-softer": "#f5f9ff", "--accent-border": "#bfdbfe" },
  indigo: { "--accent": "#4f46e5", "--accent-600": "#4f46e5", "--accent-700": "#4338ca", "--accent-soft": "#eef2ff", "--accent-softer": "#f5f5ff", "--accent-border": "#c7d2fe" },
  teal: { "--accent": "#0d9488", "--accent-600": "#0d9488", "--accent-700": "#0f766e", "--accent-soft": "#effdfa", "--accent-softer": "#f3fffd", "--accent-border": "#99f6e4" },
  slate: { "--accent": "#475569", "--accent-600": "#475569", "--accent-700": "#334155", "--accent-soft": "#f1f5f9", "--accent-softer": "#f8fafc", "--accent-border": "#cbd5e1" },
};

const ACCENTS_DARK: Record<Accent, Record<string, string>> = {
  blue: { "--accent-soft": "#16223c", "--accent-softer": "#131d33", "--accent-border": "#1e3a6b" },
  indigo: { "--accent-soft": "#1e1b4b", "--accent-softer": "#191636", "--accent-border": "#3730a3" },
  teal: { "--accent-soft": "#0c2a27", "--accent-softer": "#0a201e", "--accent-border": "#115e56" },
  slate: { "--accent-soft": "#1e293b", "--accent-softer": "#172033", "--accent-border": "#38465f" },
};

export const THEME_LABELS: Record<Theme, string> = { light: "Light", dark: "Dark" };
export const ACCENT_LABELS: Record<Accent, string> = { blue: "Blue", indigo: "Indigo", teal: "Teal", slate: "Slate" };
export const DENSITY_LABELS: Record<Density, string> = { compact: "Compact", comfortable: "Comfortable" };
export const ACCENT_COLORS: Record<Accent, string> = { blue: "#2563eb", indigo: "#4f46e5", teal: "#0d9488", slate: "#475569" };

const STORAGE_KEY = "dmp.settings";

const DEFAULTS: Settings = Object.freeze({ theme: "light", accent: "blue", density: "compact" });

let cached: Settings | null = null;
const subscribers = new Set<Subscriber>();

function read(): Settings {
  if (typeof window === "undefined") return { ...DEFAULTS };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<Settings>;
      return {
        theme: parsed.theme === "dark" ? "dark" : "light",
        accent: ACCENT_LABELS[parsed.accent as Accent] ? (parsed.accent as Accent) : DEFAULTS.accent,
        density: parsed.density === "comfortable" ? "comfortable" : "compact",
      };
    }
  } catch {
    // corrupt
  }
  return { ...DEFAULTS };
}

function persist(settings: Settings) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // unavailable
  }
}

function applyToRoot(settings: Settings) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.setAttribute("data-theme", settings.theme);
  root.setAttribute("data-density", settings.density);

  const lightTokens = ACCENTS_LIGHT[settings.accent];
  if (lightTokens) {
    Object.entries(lightTokens).forEach(([k, v]) => root.style.setProperty(k, v));
  }

  if (settings.theme === "dark") {
    const darkTokens = ACCENTS_DARK[settings.accent];
    if (darkTokens) {
      Object.entries(darkTokens).forEach(([k, v]) => root.style.setProperty(k, v));
    }
  } else {
    Object.keys(ACCENTS_DARK.blue).forEach((k) => root.style.removeProperty(k));
  }
}

function subscribe(cb: Subscriber): Unsubscribe {
  subscribers.add(cb);
  return () => { subscribers.delete(cb); };
}

function getSnapshot(): Settings {
  if (!cached) {
    cached = read();
    applyToRoot(cached);
  }
  return cached;
}

function write(next: Settings) {
  cached = next;
  persist(next);
  applyToRoot(next);
  subscribers.forEach((fn) => fn());
}

export function useSettingsStore() {
  const settings = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const updateSettings = useCallback((patch: Partial<Settings>) => {
    write({ ...getSnapshot(), ...patch });
  }, []);

  const setTheme = useCallback((theme: Theme) => updateSettings({ theme }), [updateSettings]);
  const setAccent = useCallback((accent: Accent) => updateSettings({ accent }), [updateSettings]);
  const setDensity = useCallback((density: Density) => updateSettings({ density }), [updateSettings]);

  return useMemo(
    () => ({ settings, updateSettings, setTheme, setAccent, setDensity }),
    [settings, updateSettings, setTheme, setAccent, setDensity],
  );
}

const SettingsContext = createContext<Settings | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const { settings } = useSettingsStore();
  useEffect(() => { applyToRoot(settings); }, [settings]);
  return <SettingsContext.Provider value={ settings }> { children } </SettingsContext.Provider>;
}

export function useSettings() {
  const store = useSettingsStore();
  const context = useContext(SettingsContext);
  return context ? { ...store, settings: context } : store;
}
