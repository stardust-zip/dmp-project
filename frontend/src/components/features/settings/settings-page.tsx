"use client";

import { useMemo, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Icon } from "@/components/common/icons";
import { Card, Field, Segmented } from "@/components/common/primitives";
import { useSettingsStore, type Theme, THEME_LABELS } from "@/lib/settings-store";
import { hasAnyRole, USER_MANAGEMENT_ROLES } from "@/lib/rbac";
import type { IconName } from "@/types";

type SettingsSectionId = "appearance" | "account" | "system" | "about";

type SettingsSection = {
  id: SettingsSectionId;
  label: string;
  description: string;
  icon: IconName;
};

export function SettingsContent() {
  const { session } = useAuth();
  const user = session?.user;
  const { settings, setTheme } = useSettingsStore();
  const [activeSection, setActiveSection] = useState<SettingsSectionId>("appearance");

  const isAdmin = useMemo(() => hasAnyRole(user, USER_MANAGEMENT_ROLES), [user]);

  const sections = useMemo<SettingsSection[]>(
    () => [
      {
        id: "appearance",
        label: "Appearance",
        description: "Theme preference.",
        icon: "eye",
      },
      {
        id: "account",
        label: "Account",
        description: "Profile and access details.",
        icon: "users",
      },
      ...(isAdmin
        ? [
          {
            id: "system" as const,
            label: "System",
            description: "Platform-level options.",
            icon: "wrench" as const,
          },
        ]
        : []),
      {
        id: "about",
        label: "About",
        description: "Version and stack information.",
        icon: "info",
      },
    ],
    [isAdmin],
  );

  const themeOptions = useMemo(
    () =>
      (Object.keys(THEME_LABELS) as Theme[]).map((value) => ({
        value,
        label: THEME_LABELS[value],
      })),
    [],
  );

  const active = sections.find((section) => section.id === activeSection) ?? sections[0];

  const panel =
    active.id === "appearance" ? (
      <Card title="Appearance" sub="Choose the workspace theme." icon="eye" iconTone="accent">
        <Field label="Theme">
          <Segmented<Theme> value={settings.theme} options={themeOptions} onChange={setTheme} />
        </Field>
      </Card>
    ) : active.id === "account" ? (
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
    ) : active.id === "system" ? (
      <Card title="System" sub="Platform-level configuration." icon="wrench" iconTone="orange">
        <div className="models-note">
          <Icon name="info" />
          <span>System settings and platform configuration controls will appear here in a future release (PoC v3?).</span>
        </div>
      </Card>
    ) : (
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
    );

  return (
    <div className="settings-content">
      <div className="settings-layout">
        <nav className="settings-options" aria-label="Preference sections">
          {sections.map((section) => {
            const selected = active.id === section.id;
            return (
              <button key={section.id} type="button" className={`settings-option${selected ? " active" : ""}`} onClick={() => setActiveSection(section.id)} aria-current={selected ? "page" : undefined}>
                <span className="settings-option-icon">
                  <Icon name={section.icon} />
                </span>
                <span className="settings-option-copy">
                  <b>{section.label}</b>
                  <span>{section.description}</span>
                </span>
                <Icon name="chevRight" />
              </button>
            );
          })}
        </nav>

        <section className="settings-panel" aria-live="polite">
          <div className="settings-panel-head">
            <div>
              <h3>{active.label}</h3>
              <p>{active.description}</p>
            </div>
          </div>
          {panel}
        </section>
      </div>
    </div>
  );
}

export function SettingsPage() {
  return (
    <main className="page settings-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-sub">Customize your workspace appearance and preferences.</p>
        </div>
      </div>

      <SettingsContent />
    </main>
  );
}
