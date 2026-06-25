"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";

export type Theme = "light" | "dark";
export type Accent = "blue" | "sky" | "cyan" | "teal" | "emerald" | "lime" | "amber" | "orange" | "rose" | "fuchsia" | "violet" | "indigo" | "slate";

export interface Settings {
  theme: Theme;
  accent: Accent;
}

type Subscriber = () => void;
type Unsubscribe = () => void;

const ACCENTS_LIGHT: Record<Accent, Record<string, string>> = {
  blue: { "--bg": "#eef4ff", "--accent": "#2563eb", "--accent-600": "#2563eb", "--accent-700": "#1d4ed8", "--accent-soft": "#eff6ff", "--accent-softer": "#f5f9ff", "--accent-border": "#bfdbfe", "--info": "#2563eb", "--info-soft": "#eff6ff", "--anom-low": "#2563eb", "--sb-ink-active": "#2563eb", "--on-accent": "#ffffff" },
  sky: { "--bg": "#edf8ff", "--accent": "#0284c7", "--accent-600": "#0284c7", "--accent-700": "#0369a1", "--accent-soft": "#f0f9ff", "--accent-softer": "#f7fcff", "--accent-border": "#bae6fd", "--info": "#0284c7", "--info-soft": "#f0f9ff", "--anom-low": "#0284c7", "--sb-ink-active": "#0369a1", "--on-accent": "#ffffff" },
  cyan: { "--bg": "#ecfeff", "--accent": "#0891b2", "--accent-600": "#0891b2", "--accent-700": "#0e7490", "--accent-soft": "#ecfeff", "--accent-softer": "#f5feff", "--accent-border": "#a5f3fc", "--info": "#0891b2", "--info-soft": "#ecfeff", "--anom-low": "#0891b2", "--sb-ink-active": "#0e7490", "--on-accent": "#ffffff" },
  indigo: { "--bg": "#f0f1ff", "--accent": "#4f46e5", "--accent-600": "#4f46e5", "--accent-700": "#4338ca", "--accent-soft": "#eef2ff", "--accent-softer": "#f5f5ff", "--accent-border": "#c7d2fe", "--info": "#4f46e5", "--info-soft": "#eef2ff", "--anom-low": "#4f46e5", "--sb-ink-active": "#4f46e5", "--on-accent": "#ffffff" },
  teal: { "--bg": "#edf8f6", "--accent": "#0d9488", "--accent-600": "#0d9488", "--accent-700": "#0f766e", "--accent-soft": "#effdfa", "--accent-softer": "#f3fffd", "--accent-border": "#99f6e4", "--info": "#0d9488", "--info-soft": "#effdfa", "--anom-low": "#0d9488", "--sb-ink-active": "#0d9488", "--on-accent": "#ffffff" },
  emerald: { "--bg": "#eefdf4", "--accent": "#059669", "--accent-600": "#059669", "--accent-700": "#047857", "--accent-soft": "#ecfdf5", "--accent-softer": "#f5fdf8", "--accent-border": "#a7f3d0", "--info": "#059669", "--info-soft": "#ecfdf5", "--anom-low": "#059669", "--sb-ink-active": "#047857", "--on-accent": "#ffffff" },
  lime: { "--bg": "#f5fae8", "--accent": "#65a30d", "--accent-600": "#65a30d", "--accent-700": "#4d7c0f", "--accent-soft": "#f7fee7", "--accent-softer": "#fbfef3", "--accent-border": "#bef264", "--info": "#65a30d", "--info-soft": "#f7fee7", "--anom-low": "#65a30d", "--sb-ink-active": "#4d7c0f", "--on-accent": "#ffffff" },
  amber: { "--bg": "#f6f0e6", "--accent": "#d97706", "--accent-600": "#d97706", "--accent-700": "#b45309", "--accent-soft": "#fffbeb", "--accent-softer": "#fffdf5", "--accent-border": "#fcd34d", "--info": "#d97706", "--info-soft": "#fffbeb", "--anom-low": "#d97706", "--sb-ink-active": "#b45309", "--on-accent": "#ffffff" },
  orange: { "--bg": "#fff3eb", "--accent": "#ea580c", "--accent-600": "#ea580c", "--accent-700": "#c2410c", "--accent-soft": "#fff7ed", "--accent-softer": "#fffbf7", "--accent-border": "#fdba74", "--info": "#ea580c", "--info-soft": "#fff7ed", "--anom-low": "#ea580c", "--sb-ink-active": "#c2410c", "--on-accent": "#ffffff" },
  rose: { "--bg": "#fff0f3", "--accent": "#e11d48", "--accent-600": "#e11d48", "--accent-700": "#be123c", "--accent-soft": "#fff1f2", "--accent-softer": "#fff7f8", "--accent-border": "#fda4af", "--info": "#e11d48", "--info-soft": "#fff1f2", "--anom-low": "#e11d48", "--sb-ink-active": "#be123c", "--on-accent": "#ffffff" },
  fuchsia: { "--bg": "#fdf1ff", "--accent": "#c026d3", "--accent-600": "#c026d3", "--accent-700": "#a21caf", "--accent-soft": "#fdf4ff", "--accent-softer": "#fefaff", "--accent-border": "#f0abfc", "--info": "#c026d3", "--info-soft": "#fdf4ff", "--anom-low": "#c026d3", "--sb-ink-active": "#a21caf", "--on-accent": "#ffffff" },
  violet: { "--bg": "#f5f0ff", "--accent": "#7c3aed", "--accent-600": "#7c3aed", "--accent-700": "#6d28d9", "--accent-soft": "#f5f3ff", "--accent-softer": "#faf8ff", "--accent-border": "#ddd6fe", "--info": "#7c3aed", "--info-soft": "#f5f3ff", "--anom-low": "#7c3aed", "--sb-ink-active": "#6d28d9", "--on-accent": "#ffffff" },
  slate: { "--bg": "#eef1f5", "--accent": "#475569", "--accent-600": "#475569", "--accent-700": "#334155", "--accent-soft": "#f1f5f9", "--accent-softer": "#f8fafc", "--accent-border": "#cbd5e1", "--info": "#475569", "--info-soft": "#f1f5f9", "--anom-low": "#475569", "--sb-ink-active": "#334155", "--on-accent": "#ffffff" },
};

const ACCENTS_DARK: Record<Accent, Record<string, string>> = {
  blue: { "--bg": "#0a1018", "--surface": "#121b27", "--surface-2": "#1b2635", "--surface-3": "#263649", "--border": "#34475f", "--border-2": "#506882", "--sb-bg": "#0d1520", "--sb-border": "#2b3b50", "--sb-hover-bg": "#1b2635", "--topbar-bg": "#0d1520", "--accent": "#60a5fa", "--accent-600": "#60a5fa", "--accent-700": "#93c5fd", "--accent-soft": "#12243d", "--accent-softer": "#0f1b2e", "--accent-border": "#2563eb", "--info": "#60a5fa", "--info-soft": "#12243d", "--anom-low": "#60a5fa", "--sb-ink-active": "#bfdbfe", "--on-accent": "#07111f" },
  sky: { "--bg": "#07131e", "--surface": "#101d2b", "--surface-2": "#182a3c", "--surface-3": "#223a52", "--border": "#31526f", "--border-2": "#4b7392", "--sb-bg": "#0b1926", "--sb-border": "#29455e", "--sb-hover-bg": "#182a3c", "--topbar-bg": "#0b1926", "--accent": "#38bdf8", "--accent-600": "#38bdf8", "--accent-700": "#7dd3fc", "--accent-soft": "#082f49", "--accent-softer": "#082334", "--accent-border": "#0369a1", "--info": "#38bdf8", "--info-soft": "#082f49", "--anom-low": "#38bdf8", "--sb-ink-active": "#bae6fd", "--on-accent": "#082f49" },
  cyan: { "--bg": "#061416", "--surface": "#0e2024", "--surface-2": "#162d33", "--surface-3": "#203f47", "--border": "#305b64", "--border-2": "#497a85", "--sb-bg": "#091a1e", "--sb-border": "#294b53", "--sb-hover-bg": "#162d33", "--topbar-bg": "#091a1e", "--accent": "#22d3ee", "--accent-600": "#22d3ee", "--accent-700": "#67e8f9", "--accent-soft": "#083344", "--accent-softer": "#062932", "--accent-border": "#0e7490", "--info": "#22d3ee", "--info-soft": "#083344", "--anom-low": "#22d3ee", "--sb-ink-active": "#a5f3fc", "--on-accent": "#062b36" },
  indigo: { "--bg": "#0f101c", "--surface": "#171829", "--surface-2": "#20223a", "--surface-3": "#2c2e4d", "--border": "#3f4268", "--border-2": "#5e6290", "--sb-bg": "#121322", "--sb-border": "#333655", "--sb-hover-bg": "#20223a", "--topbar-bg": "#121322", "--accent": "#818cf8", "--accent-600": "#818cf8", "--accent-700": "#a5b4fc", "--accent-soft": "#1e1b3f", "--accent-softer": "#17152f", "--accent-border": "#6366f1", "--info": "#818cf8", "--info-soft": "#1e1b3f", "--anom-low": "#818cf8", "--sb-ink-active": "#c7d2fe", "--on-accent": "#0b1024" },
  teal: { "--bg": "#071311", "--surface": "#101f1d", "--surface-2": "#182c29", "--surface-3": "#233d39", "--border": "#335752", "--border-2": "#4d746e", "--sb-bg": "#0b1917", "--sb-border": "#29443f", "--sb-hover-bg": "#182c29", "--topbar-bg": "#0b1917", "--accent": "#2dd4bf", "--accent-600": "#2dd4bf", "--accent-700": "#5eead4", "--accent-soft": "#0c2a27", "--accent-softer": "#091f1d", "--accent-border": "#0f766e", "--info": "#2dd4bf", "--info-soft": "#0c2a27", "--anom-low": "#2dd4bf", "--sb-ink-active": "#99f6e4", "--on-accent": "#041412" },
  emerald: { "--bg": "#071410", "--surface": "#10211b", "--surface-2": "#182f26", "--surface-3": "#234235", "--border": "#335f4e", "--border-2": "#4d806c", "--sb-bg": "#0b1a15", "--sb-border": "#294f41", "--sb-hover-bg": "#182f26", "--topbar-bg": "#0b1a15", "--accent": "#34d399", "--accent-600": "#34d399", "--accent-700": "#6ee7b7", "--accent-soft": "#063721", "--accent-softer": "#052819", "--accent-border": "#047857", "--info": "#34d399", "--info-soft": "#063721", "--anom-low": "#34d399", "--sb-ink-active": "#a7f3d0", "--on-accent": "#052e1a" },
  lime: { "--bg": "#111407", "--surface": "#1d2110", "--surface-2": "#2a3018", "--surface-3": "#3a4322", "--border": "#566133", "--border-2": "#75844c", "--sb-bg": "#171a0b", "--sb-border": "#454f29", "--sb-hover-bg": "#2a3018", "--topbar-bg": "#171a0b", "--accent": "#a3e635", "--accent-600": "#a3e635", "--accent-700": "#bef264", "--accent-soft": "#263609", "--accent-softer": "#1e2a08", "--accent-border": "#4d7c0f", "--info": "#a3e635", "--info-soft": "#263609", "--anom-low": "#a3e635", "--sb-ink-active": "#d9f99d", "--on-accent": "#182505" },
  amber: { "--bg": "#11100f", "--surface": "#1b1815", "--surface-2": "#24201c", "--surface-3": "#312b25", "--border": "#413a33", "--border-2": "#5c5147", "--sb-bg": "#161310", "--sb-border": "#332d27", "--sb-hover-bg": "#24201c", "--topbar-bg": "#161310", "--accent": "#f59e0b", "--accent-600": "#f59e0b", "--accent-700": "#fbbf24", "--accent-soft": "#33240f", "--accent-softer": "#261d12", "--accent-border": "#b45309", "--info": "#f59e0b", "--info-soft": "#33240f", "--anom-low": "#f59e0b", "--sb-ink-active": "#fde68a", "--on-accent": "#1c1204" },
  orange: { "--bg": "#160f0a", "--surface": "#241811", "--surface-2": "#33231a", "--surface-3": "#462f23", "--border": "#654534", "--border-2": "#875f49", "--sb-bg": "#1b130d", "--sb-border": "#4e372a", "--sb-hover-bg": "#33231a", "--topbar-bg": "#1b130d", "--accent": "#fb923c", "--accent-600": "#fb923c", "--accent-700": "#fdba74", "--accent-soft": "#3a1f0b", "--accent-softer": "#2b1809", "--accent-border": "#c2410c", "--info": "#fb923c", "--info-soft": "#3a1f0b", "--anom-low": "#fb923c", "--sb-ink-active": "#fed7aa", "--on-accent": "#241204" },
  rose: { "--bg": "#170f12", "--surface": "#22171b", "--surface-2": "#2e2025", "--surface-3": "#3e2b31", "--border": "#563943", "--border-2": "#765260", "--sb-bg": "#1b1216", "--sb-border": "#422d34", "--sb-hover-bg": "#2e2025", "--topbar-bg": "#1b1216", "--accent": "#fb7185", "--accent-600": "#fb7185", "--accent-700": "#fda4af", "--accent-soft": "#351923", "--accent-softer": "#28151c", "--accent-border": "#be123c", "--info": "#fb7185", "--info-soft": "#351923", "--anom-low": "#fb7185", "--sb-ink-active": "#fecdd3", "--on-accent": "#1d080d" },
  fuchsia: { "--bg": "#160d17", "--surface": "#241626", "--surface-2": "#331f36", "--surface-3": "#462c4a", "--border": "#65406b", "--border-2": "#875a8e", "--sb-bg": "#1b111d", "--sb-border": "#4f3354", "--sb-hover-bg": "#331f36", "--topbar-bg": "#1b111d", "--accent": "#e879f9", "--accent-600": "#e879f9", "--accent-700": "#f0abfc", "--accent-soft": "#3b123f", "--accent-softer": "#2c0f31", "--accent-border": "#a21caf", "--info": "#e879f9", "--info-soft": "#3b123f", "--anom-low": "#e879f9", "--sb-ink-active": "#f5d0fe", "--on-accent": "#25072a" },
  violet: { "--bg": "#100e1c", "--surface": "#1b172c", "--surface-2": "#27213e", "--surface-3": "#352d55", "--border": "#4d4276", "--border-2": "#695d99", "--sb-bg": "#141123", "--sb-border": "#3d345f", "--sb-hover-bg": "#27213e", "--topbar-bg": "#141123", "--accent": "#a78bfa", "--accent-600": "#a78bfa", "--accent-700": "#c4b5fd", "--accent-soft": "#2e1a57", "--accent-softer": "#231542", "--accent-border": "#6d28d9", "--info": "#a78bfa", "--info-soft": "#2e1a57", "--anom-low": "#a78bfa", "--sb-ink-active": "#ddd6fe", "--on-accent": "#160a2e" },
  slate: { "--bg": "#111111", "--surface": "#1a1918", "--surface-2": "#242220", "--surface-3": "#302d2a", "--border": "#423d38", "--border-2": "#5d554d", "--sb-bg": "#151412", "--sb-border": "#34302c", "--sb-hover-bg": "#242220", "--topbar-bg": "#151412", "--accent": "#d6d3d1", "--accent-600": "#d6d3d1", "--accent-700": "#f5f5f4", "--accent-soft": "#2d2925", "--accent-softer": "#24211e", "--accent-border": "#78716c", "--info": "#d6d3d1", "--info-soft": "#2d2925", "--anom-low": "#d6d3d1", "--sb-ink-active": "#f5f5f4", "--on-accent": "#171412" },
};

const MANAGED_THEME_VARS = Array.from(
  new Set([
    ...Object.values(ACCENTS_LIGHT).flatMap((tokens) => Object.keys(tokens)),
    ...Object.values(ACCENTS_DARK).flatMap((tokens) => Object.keys(tokens)),
  ]),
);

export const THEME_LABELS: Record<Theme, string> = { light: "Light", dark: "Dark" };

const STORAGE_KEY = "dmp.settings";

const DEFAULTS: Settings = Object.freeze({ theme: "light", accent: "blue" });

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
        accent: DEFAULTS.accent,
      };
    }
  } catch {
    // corrupt
  }
  return { ...DEFAULTS };
}

function normalize(settings: Settings): Settings {
  return {
    theme: settings.theme === "dark" ? "dark" : "light",
    accent: DEFAULTS.accent,
  };
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
  root.removeAttribute("data-density");
  MANAGED_THEME_VARS.forEach((name) => root.style.removeProperty(name));

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
  const normalized = normalize(next);
  cached = normalized;
  persist(normalized);
  applyToRoot(normalized);
  subscribers.forEach((fn) => fn());
}

export function useSettingsStore() {
  const settings = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const updateSettings = useCallback((patch: Partial<Settings>) => {
    write({ ...getSnapshot(), ...patch });
  }, []);

  const setTheme = useCallback((theme: Theme) => updateSettings({ theme }), [updateSettings]);

  return useMemo(
    () => ({ settings, updateSettings, setTheme }),
    [settings, updateSettings, setTheme],
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
