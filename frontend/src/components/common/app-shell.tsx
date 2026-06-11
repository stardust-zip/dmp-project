"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Icon } from "@/components/common/icons";
import { MAIN_NAV, hasAnyRole } from "@/lib/rbac";

const ACCENTS = {
  blue: { "--accent": "#2563eb", "--accent-600": "#2563eb", "--accent-700": "#1d4ed8", "--accent-soft": "#eff6ff", "--accent-softer": "#f5f9ff", "--accent-border": "#bfdbfe" },
  indigo: { "--accent": "#4f46e5", "--accent-600": "#4f46e5", "--accent-700": "#4338ca", "--accent-soft": "#eef2ff", "--accent-softer": "#f5f5ff", "--accent-border": "#c7d2fe" },
  teal: { "--accent": "#0d9488", "--accent-600": "#0d9488", "--accent-700": "#0f766e", "--accent-soft": "#effdfa", "--accent-softer": "#f3fffd", "--accent-border": "#99f6e4" },
  slate: { "--accent": "#475569", "--accent-600": "#475569", "--accent-700": "#334155", "--accent-soft": "#f1f5f9", "--accent-softer": "#f8fafc", "--accent-border": "#cbd5e1" },
};

const ACCENT_DARK = {
  blue: { "--accent-soft": "#16223c", "--accent-softer": "#131d33", "--accent-border": "#1e3a6b" },
  indigo: { "--accent-soft": "#1e1b4b", "--accent-softer": "#191636", "--accent-border": "#3730a3" },
  teal: { "--accent-soft": "#0c2a27", "--accent-softer": "#0a201e", "--accent-border": "#115e56" },
  slate: { "--accent-soft": "#1e293b", "--accent-softer": "#172033", "--accent-border": "#38465f" },
};

const DATE_RANGES = ["Last 24 hours", "Last 7 days", "Last 30 days", "This month", "Quarter to date", "Custom range..."];

function routeLabel(pathname: string) {
  if (pathname.startsWith("/anomaly")) return "Anomaly Detection";
  if (pathname.startsWith("/forecast")) return "Forecasting";
  if (pathname.startsWith("/prediction")) return "Prediction";
  if (pathname.startsWith("/models")) return "AI Engineering";
  if (pathname.startsWith("/assets")) return "Assets";
  if (pathname.startsWith("/users")) return "User Management";
  return "Dashboard";
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { session, signOut } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [dateRange, setDateRange] = useState("Last 24 hours");
  const [dateOpen, setDateOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const meta = useMemo(() => routeLabel(pathname), [pathname]);
  const user = session?.user;
  const navItems = useMemo(() => MAIN_NAV.filter((item) => hasAnyRole(user, item.roles)), [user]);
  const initials = useMemo(() => {
    const source = user?.fullName || user?.email || "User";
    return source
      .split(/[\s@._-]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join("");
  }, [user]);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", "light");
    root.setAttribute("data-density", "compact");
    Object.entries(ACCENTS.blue).forEach(([key, value]) => root.style.setProperty(key, value));
    Object.entries(ACCENT_DARK.blue).forEach(([key]) => root.style.removeProperty(key));
  }, []);

  useEffect(() => {
    const close = () => {
      setDateOpen(false);
      setProfileOpen(false);
    };
    if (dateOpen || profileOpen) {
      window.addEventListener("click", close);
      return () => window.removeEventListener("click", close);
    }
    return undefined;
  }, [dateOpen, profileOpen]);

  if (pathname === "/login") {
    return children;
  }

  return (
    <div className={`app${collapsed ? " collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="sb-brand">
          <div className="sb-logo">
            <Icon name="bolt" />
          </div>
          <div className="sb-brand-txt">
            <b>Data Platform</b>
            <span>Energy Management</span>
          </div>
        </div>

        <div className="sb-section">Monitoring</div>
        <nav className="sb-nav">
          {navItems.map((item) => {
            const active = pathname === item.href || (pathname === "/" && item.href === "/dashboard");
            return (
              <Link key={item.href} className={`sb-item${active ? " active" : ""}`} href={item.href} title={item.label}>
                <Icon name={item.icon} />
                <span>{item.label}</span>
                {item.badge && <span className="sb-badge">{item.badge}</span>}
              </Link>
            );
          })}
        </nav>

        <div className="sb-section">Workspace</div>
        <nav className="sb-nav">
          <button className="sb-item" title="Reports">
            <Icon name="doc" />
            <span>Reports</span>
          </button>
          <button className="sb-item" title="Settings">
            <Icon name="settings" />
            <span>Settings</span>
          </button>
        </nav>

        <div className="sb-foot">
          <i className="sb-dot" />
          <span className="sb-foot-txt">
            All systems operational <b style={{ color: "var(--muted)" }}>PoC v1.0</b>
          </span>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="icon-btn" onClick={() => setCollapsed((value) => !value)} title="Toggle sidebar">
            <Icon name="panelLeft" />
          </button>
          <div className="crumbs">
            <span>Energy Suite</span>
            <Icon name="chevRight" />
            <b>{meta}</b>
          </div>
          <div className="topbar-spacer" />

          <div className="search">
            <Icon name="search" />
            <input placeholder="Search buildings, meters, alerts..." />
            <kbd>Ctrl K</kbd>
          </div>

          <div style={{ position: "relative" }} onClick={(event) => event.stopPropagation()}>
            <div
              className="daterange"
              onClick={() => {
                setDateOpen((open) => !open);
                setProfileOpen(false);
              }}
            >
              <Icon name="calendar" />
              <span>{dateRange}</span>
              <Icon name="chevDown" className="chev" />
            </div>
            {dateOpen && (
              <div style={{ position: "absolute", top: 40, right: 0, width: 196, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, boxShadow: "var(--shadow-lg)", padding: 5, zIndex: 40 }}>
                {DATE_RANGES.map((range) => (
                  <button
                    key={range}
                    className="sb-item"
                    style={{ height: 32, fontSize: 12.5, color: range === dateRange ? "var(--accent-600)" : "var(--ink-2)", fontWeight: range === dateRange ? 600 : 500 }}
                    onClick={() => {
                      setDateRange(range);
                      setDateOpen(false);
                    }}
                  >
                    <span>{range}</span>
                    {range === dateRange && <Icon name="check" style={{ width: 15, height: 15, marginLeft: "auto" }} />}
                  </button>
                ))}
              </div>
            )}
          </div>

          <button className="icon-btn" title="Alerts" style={{ position: "relative" }}>
            <Icon name="bell" />
            <span style={{ position: "absolute", top: 6, right: 6, width: 7, height: 7, borderRadius: "50%", background: "var(--red)", boxShadow: "0 0 0 2px var(--topbar-bg)" }} />
          </button>
          <div className="divider" />

          <div style={{ position: "relative" }} onClick={(event) => event.stopPropagation()}>
            <div
              className="profile"
              onClick={() => {
                setProfileOpen((open) => !open);
                setDateOpen(false);
              }}
            >
              <div className="avatar">{initials}</div>
              <div className="profile-meta">
                <b>{user?.fullName ?? "User"}</b>
                <span>{user?.roleLabel ?? "Authenticated"}</span>
              </div>
              <Icon name="chevDown" style={{ width: 14, height: 14, color: "var(--muted)" }} />
            </div>
            {profileOpen && (
              <div style={{ position: "absolute", top: 44, right: 0, width: 210, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, boxShadow: "var(--shadow-lg)", padding: 5, zIndex: 40 }}>
                <div style={{ padding: "8px 11px 9px", borderBottom: "1px solid var(--border)", marginBottom: 4 }}>
                  <div style={{ fontWeight: 650, fontSize: 13 }}>{user?.fullName ?? "User"}</div>
                  <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{user?.email}</div>
                  <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{user?.roleLabel}</div>
                </div>
                {[
                  ["users", "Account"],
                  ["settings", "Preferences"],
                  ["help", "Help & docs"],
                ].map(([icon, label]) => (
                  <button key={label} className="sb-item" style={{ height: 32, fontSize: 12.5 }}>
                    <Icon name={icon as "users" | "settings" | "help"} />
                    <span>{label}</span>
                  </button>
                ))}
                <div style={{ borderTop: "1px solid var(--border)", marginTop: 4, paddingTop: 4 }}>
                  <button className="sb-item" style={{ height: 32, fontSize: 12.5, color: "var(--red)" }} onClick={signOut}>
                    <Icon name="external" />
                    <span>Sign out</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        </header>

        <div className="scroll">{children}</div>
      </div>
    </div>
  );
}
