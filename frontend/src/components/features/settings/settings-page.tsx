"use client";

import { useMemo } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Icon } from "@/components/common/icons";
import { Card, Field, Segmented } from "@/components/common/primitives";
import { useSettingsStore, type Accent, type Density, type Theme, ACCENT_COLORS, ACCENT_LABELS, DENSITY_LABELS, THEME_LABELS } from "@/lib/settings-store";
import { hasAnyRole, USER_MANAGEMENT_ROLES } from "@/lib/rbac";

export function SettingsPage() {
  const { session } = useAuth();
  const user = session?.user;
  const { settings, setTheme, setAccent, setDensity } = useSettingsStore();

  const isAdmin = useMemo(() => hasAnyRole(user, USER_MANAGEMENT_ROLES), [user]);

  const themeOptions = useMemo(
    () =>
      (Object.keys(THEME_LABELS) as Theme[]).map((value) => ({
        value,
        label: THEME_LABELS[value],
      })),
    [],
  );

  const densityOptions = useMemo(
    () =>
      (Object.keys(DENSITY_LABELS) as Density[]).map((value) => ({
        value,
        label: DENSITY_LABELS[value],
      })),
    [],
  );

  return (
    <main className="page settings-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-sub">Customize your workspace appearance and preferences.</p>
        </div>
      </div>

      <div className="settings-grid">
        {/* Appearance */}
        <Card title="Appearance" sub="Theme, accent colour, and UI density." icon="eye" iconTone="accent">
          <Field label="Theme">
            <Segmented<Theme> value={settings.theme} options={themeOptions} onChange={setTheme} />
          </Field>

          <Field label="Accent colour">
            <div className="accent-palette">
              {(Object.keys(ACCENT_COLORS) as Accent[]).map((key) => {
                const color = ACCENT_COLORS[key];
                const selected = settings.accent === key;
                return (
                  <button
                    key={key}
                    type="button"
                    className={`accent-swatch${selected ? " selected" : ""}`}
                    style={{ "--swatch-color": color } as React.CSSProperties}
                    onClick={() => setAccent(key)}
                    aria-pressed={selected}
                  >
                    <span className="swatch-dot" style={{ background: color }} />
                    <span className="swatch-label">{ACCENT_LABELS[key]}</span>
                    {selected && <Icon name="check" className="swatch-check" />}
                  </button>
                );
              })}
            </div>
          </Field>

          <Field label="Density">
            <Segmented<Density> value={settings.density} options={densityOptions} onChange={setDensity} />
          </Field>
        </Card>

        {/* Account */}
        <Card title="Account" sub="Your profile and role information." icon="users" iconTone="slate">
          <div className="dl">
            <dt>Name</dt>
            <dd>{user?.fullName ?? "—"}</dd>

            <dt>Email</dt>
            <dd>{user?.email ?? "—"}</dd>

            <dt>Role</dt>
            <dd>
              <span className="badge badge-neutral">
                <i className="bdot" />
                {user?.roleLabel ?? "—"}
              </span>
            </dd>

            <dt>Contact number</dt>
            <dd>{user?.contactNumber || "—"}</dd>

            <dt>Scope</dt>
            <dd>
              {user?.isGlobalAdmin
                ? "Global administrator"
                : user?.assignedSiteIds && user.assignedSiteIds.length > 0
                  ? `${user.assignedSiteIds.length} site${user.assignedSiteIds.length !== 1 ? "s" : ""} assigned`
                  : "No sites assigned"}
            </dd>
          </div>
        </Card>

        {/* System — admin only */}
        {isAdmin && (
          <Card title="System" sub="Platform-level configuration." icon="wrench" iconTone="orange">
            <div className="models-note">
              <Icon name="info" />
              <span>System settings and platform configuration controls will appear here in a future release.</span>
            </div>
          </Card>
        )}

        {/* About */}
        <Card title="About" sub="Application version and information." icon="info" iconTone="slate">
          <div className="dl">
            <dt>Application</dt>
            <dd>Data Management Platform</dd>
            <dt>Version</dt>
            <dd>PoC v1.0</dd>
            <dt>Stack</dt>
            <dd>Next.js + FastAPI + PostgreSQL</dd>
          </div>
        </Card>
      </div>
    </main>
  );
}
