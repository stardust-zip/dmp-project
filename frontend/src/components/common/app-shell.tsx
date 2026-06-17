"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Icon } from "@/components/common/icons";
import { Modal } from "@/components/common/primitives";
import { SettingsContent } from "@/components/features/settings/settings-page";
import { MAIN_NAV, hasAnyRole } from "@/lib/rbac";
import { useSettingsStore } from "@/lib/settings-store";

function routeLabel(pathname: string) {
  if (pathname.startsWith("/anomaly")) return "Anomaly Detection";
  if (pathname.startsWith("/forecast")) return "Forecasting";
  if (pathname.startsWith("/models")) return "AI Engineering";
  if (pathname.startsWith("/assets")) return "Assets";
  if (pathname.startsWith("/users")) return "User Management";
  if (pathname.startsWith("/settings")) return "Settings";
  return "Dashboard";
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { session, signOut } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
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

  // Settings are applied to <html> automatically by useSettingsStore on mount
  useSettingsStore();

  useEffect(() => {
    if (!profileOpen) return;
    const close = () => setProfileOpen(false);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [profileOpen]);

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

          <button className="icon-btn" title="Alerts" style={{ position: "relative" }}>
            <Icon name="bell" />
            <span style={{ position: "absolute", top: 6, right: 6, width: 7, height: 7, borderRadius: "50%", background: "var(--red)", boxShadow: "0 0 0 2px var(--topbar-bg)" }} />
          </button>
          <div className="divider" />

          <div className="account-menu-wrap" onClick={(event) => event.stopPropagation()}>
            <div
              className="profile"
              onClick={() => setProfileOpen((open) => !open)}
            >
              <div className="avatar">{initials}</div>
              <div className="profile-meta">
                <b>{user?.fullName ?? "User"}</b>
                <span>{user?.roleLabel ?? "Authenticated"}</span>
              </div>
              <Icon name="chevDown" style={{ width: 14, height: 14, color: "var(--muted)" }} />
            </div>
            {profileOpen && (
              <div className="account-menu">
                <div className="account-menu-head">
                  <div className="account-menu-name">{user?.fullName ?? "User"}</div>
                  <div>{user?.email}</div>
                  <div>{user?.roleLabel}</div>
                </div>
                <button
                  className="account-menu-item"
                  type="button"
                  onClick={() => {
                    setProfileOpen(false);
                    setSettingsOpen(true);
                  }}
                >
                  <Icon name="settings" />
                  <span>Preferences</span>
                </button>
                <button
                  className="account-menu-item"
                  type="button"
                  onClick={() => {
                    window.open("https://github.com/stardust-zip/dmp-project", "_blank", "noopener,noreferrer");
                    setProfileOpen(false);
                  }}
                >
                  <Icon name="help" />
                  <span>Help & docs</span>
                </button>
                <div className="account-menu-sep">
                  <button className="account-menu-item danger" type="button" onClick={signOut}>
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
      {settingsOpen && (
        <Modal
          title="Preferences"
          description="Tune this workspace without leaving what you were doing."
          className="settings-modal"
          onClose={() => setSettingsOpen(false)}
        >
          <SettingsContent />
        </Modal>
      )}
    </div>
  );
}
