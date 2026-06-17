"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";

export type Theme = "light" | "dark";
export type Accent = "blue" | "indigo" | "teal" | "amber" | "rose" | "slate";
export type Density = "compact" | "comfortable";

export interface Settings {
  theme: Theme;
  accent: Accent;
  density: Density;
}

type Subscriber = () => void;
type Unsubscribe = () => void;

const ACCENTS_LIGHT: Record<Accent, Record<string, string>> = {
  blue: { "--bg": "#eef4ff", "--accent": "#2563eb", "--accent-600": "#2563eb", "--accent-700": "#1d4ed8", "--accent-soft": "#eff6ff", "--accent-softer": "#f5f9ff", "--accent-border": "#bfdbfe", "--info": "#2563eb", "--info-soft": "#eff6ff", "--anom-low": "#2563eb", "--sb-ink-active": "#2563eb", "--on-accent": "#ffffff" },
  indigo: { "--bg": "#f0f1ff", "--accent": "#4f46e5", "--accent-600": "#4f46e5", "--accent-700": "#4338ca", "--accent-soft": "#eef2ff", "--accent-softer": "#f5f5ff", "--accent-border": "#c7d2fe", "--info": "#4f46e5", "--info-soft": "#eef2ff", "--anom-low": "#4f46e5", "--sb-ink-active": "#4f46e5", "--on-accent": "#ffffff" },
  teal: { "--bg": "#edf8f6", "--accent": "#0d9488", "--accent-600": "#0d9488", "--accent-700": "#0f766e", "--accent-soft": "#effdfa", "--accent-softer": "#f3fffd", "--accent-border": "#99f6e4", "--info": "#0d9488", "--info-soft": "#effdfa", "--anom-low": "#0d9488", "--sb-ink-active": "#0d9488", "--on-accent": "#ffffff" },
  amber: { "--bg": "#f6f0e6", "--accent": "#d97706", "--accent-600": "#d97706", "--accent-700": "#b45309", "--accent-soft": "#fffbeb", "--accent-softer": "#fffdf5", "--accent-border": "#fcd34d", "--info": "#d97706", "--info-soft": "#fffbeb", "--anom-low": "#d97706", "--sb-ink-active": "#b45309", "--on-accent": "#ffffff" },
  rose: { "--bg": "#fff0f3", "--accent": "#e11d48", "--accent-600": "#e11d48", "--accent-700": "#be123c", "--accent-soft": "#fff1f2", "--accent-softer": "#fff7f8", "--accent-border": "#fda4af", "--info": "#e11d48", "--info-soft": "#fff1f2", "--anom-low": "#e11d48", "--sb-ink-active": "#be123c", "--on-accent": "#ffffff" },
  slate: { "--bg": "#eef1f5", "--accent": "#475569", "--accent-600": "#475569", "--accent-700": "#334155", "--accent-soft": "#f1f5f9", "--accent-softer": "#f8fafc", "--accent-border": "#cbd5e1", "--info": "#475569", "--info-soft": "#f1f5f9", "--anom-low": "#475569", "--sb-ink-active": "#334155", "--on-accent": "#ffffff" },
};

const ACCENTS_DARK: Record<Accent, Record<string, string>> = {
  blue: { "--bg": "#0a1018", "--surface": "#121b27", "--surface-2": "#1b2635", "--surface-3": "#263649", "--border": "#34475f", "--border-2": "#506882", "--sb-bg": "#0d1520", "--sb-border": "#2b3b50", "--sb-hover-bg": "#1b2635", "--topbar-bg": "#0d1520", "--accent": "#60a5fa", "--accent-600": "#60a5fa", "--accent-700": "#93c5fd", "--accent-soft": "#12243d", "--accent-softer": "#0f1b2e", "--accent-border": "#2563eb", "--info": "#60a5fa", "--info-soft": "#12243d", "--anom-low": "#60a5fa", "--sb-ink-active": "#bfdbfe", "--on-accent": "#07111f" },
  indigo: { "--bg": "#0f101c", "--surface": "#171829", "--surface-2": "#20223a", "--surface-3": "#2c2e4d", "--border": "#3f4268", "--border-2": "#5e6290", "--sb-bg": "#121322", "--sb-border": "#333655", "--sb-hover-bg": "#20223a", "--topbar-bg": "#121322", "--accent": "#818cf8", "--accent-600": "#818cf8", "--accent-700": "#a5b4fc", "--accent-soft": "#1e1b3f", "--accent-softer": "#17152f", "--accent-border": "#6366f1", "--info": "#818cf8", "--info-soft": "#1e1b3f", "--anom-low": "#818cf8", "--sb-ink-active": "#c7d2fe", "--on-accent": "#0b1024" },
  teal: { "--bg": "#071311", "--surface": "#101f1d", "--surface-2": "#182c29", "--surface-3": "#233d39", "--border": "#335752", "--border-2": "#4d746e", "--sb-bg": "#0b1917", "--sb-border": "#29443f", "--sb-hover-bg": "#182c29", "--topbar-bg": "#0b1917", "--accent": "#2dd4bf", "--accent-600": "#2dd4bf", "--accent-700": "#5eead4", "--accent-soft": "#0c2a27", "--accent-softer": "#091f1d", "--accent-border": "#0f766e", "--info": "#2dd4bf", "--info-soft": "#0c2a27", "--anom-low": "#2dd4bf", "--sb-ink-active": "#99f6e4", "--on-accent": "#041412" },
  amber: { "--bg": "#11100f", "--surface": "#1b1815", "--surface-2": "#24201c", "--surface-3": "#312b25", "--border": "#413a33", "--border-2": "#5c5147", "--sb-bg": "#161310", "--sb-border": "#332d27", "--sb-hover-bg": "#24201c", "--topbar-bg": "#161310", "--accent": "#f59e0b", "--accent-600": "#f59e0b", "--accent-700": "#fbbf24", "--accent-soft": "#33240f", "--accent-softer": "#261d12", "--accent-border": "#b45309", "--info": "#f59e0b", "--info-soft": "#33240f", "--anom-low": "#f59e0b", "--sb-ink-active": "#fde68a", "--on-accent": "#1c1204" },
  rose: { "--bg": "#170f12", "--surface": "#22171b", "--surface-2": "#2e2025", "--surface-3": "#3e2b31", "--border": "#563943", "--border-2": "#765260", "--sb-bg": "#1b1216", "--sb-border": "#422d34", "--sb-hover-bg": "#2e2025", "--topbar-bg": "#1b1216", "--accent": "#fb7185", "--accent-600": "#fb7185", "--accent-700": "#fda4af", "--accent-soft": "#351923", "--accent-softer": "#28151c", "--accent-border": "#be123c", "--info": "#fb7185", "--info-soft": "#351923", "--anom-low": "#fb7185", "--sb-ink-active": "#fecdd3", "--on-accent": "#1d080d" },
  slate: { "--bg": "#111111", "--surface": "#1a1918", "--surface-2": "#242220", "--surface-3": "#302d2a", "--border": "#423d38", "--border-2": "#5d554d", "--sb-bg": "#151412", "--sb-border": "#34302c", "--sb-hover-bg": "#242220", "--topbar-bg": "#151412", "--accent": "#d6d3d1", "--accent-600": "#d6d3d1", "--accent-700": "#f5f5f4", "--accent-soft": "#2d2925", "--accent-softer": "#24211e", "--accent-border": "#78716c", "--info": "#d6d3d1", "--info-soft": "#2d2925", "--anom-low": "#d6d3d1", "--sb-ink-active": "#f5f5f4", "--on-accent": "#171412" },
};

export const THEME_LABELS: Record<Theme, string> = { light: "Light", dark: "Dark" };
export const ACCENT_LABELS: Record<Accent, string> = { blue: "Blue", indigo: "Indigo", teal: "Teal", amber: "Amber", rose: "Rose", slate: "Slate" };
export const DENSITY_LABELS: Record<Density, string> = { compact: "Compact", comfortable: "Comfortable" };
export const ACCENT_COLORS: Record<Accent, string> = { blue: "#2563eb", indigo: "#4f46e5", teal: "#0d9488", amber: "#d97706", rose: "#e11d48", slate: "#475569" };

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
