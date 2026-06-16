"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Icon } from "@/components/common/icons";
import { Card, Field, Select } from "@/components/common/primitives";
import { displayLocationName, humanizeIdentifier } from "@/lib/format";
import { getLocationOptions, type LocationOption } from "@/lib/models-api";
import { UserLocationPicker } from "@/components/features/users/user-location-picker";
import {
  USER_ROLES,
  USER_STATUSES,
  createUser,
  deleteUser,
  getUsers,
  isManagedUserRole,
  managedRoleLabel,
  updateUserRole,
  type CreateUserPayload,
  type ManagedUser,
  type ManagedUserRole,
  type ManagedUserStatus,
  type UpdateUserRolePayload,
} from "@/lib/users-api";

type RoleFilter = "all" | ManagedUserRole;

const EMPTY_FORM: CreateUserPayload = {
  email: "",
  full_name: "",
  password: "",
  role: "Operator",
  status: "Off_Duty",
  contact_number: "",
  assigned_site_ids: [],
  is_global_admin: false,
};

const RECENT_LOCATIONS_KEY = "dmp.recent-location-ids";

interface RecentLocationEntry {
  id: string;
  name: string;
}

function loadRecentLocationEntries(): RecentLocationEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(RECENT_LOCATIONS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (entry: unknown): entry is RecentLocationEntry =>
        typeof entry === "object" && entry !== null && typeof (entry as RecentLocationEntry).id === "string" && typeof (entry as RecentLocationEntry).name === "string",
    );
  } catch {
    return [];
  }
}

function saveRecentLocationEntries(locations: LocationOption[]) {
  if (typeof window === "undefined") return;
  const current = loadRecentLocationEntries();
  const updated = [
    ...locations.map((loc) => ({ id: loc.id, name: loc.name ?? loc.id })),
    ...current.filter((entry) => !locations.some((loc) => loc.id === entry.id)),
  ].slice(0, 10);
  window.localStorage.setItem(RECENT_LOCATIONS_KEY, JSON.stringify(updated));
}

function userInitials(user: ManagedUser) {
  const source = user.full_name || user.email;
  return source
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
}

interface PasswordRequirement {
  label: string;
  met: boolean;
}

function passwordRequirements(password: string): PasswordRequirement[] {
  return [
    { label: "At least 8 characters", met: password.length >= 8 },
    { label: "One uppercase letter (A–Z)", met: /[A-Z]/.test(password) },
    { label: "One lowercase letter (a–z)", met: /[a-z]/.test(password) },
    { label: "One number (0–9)", met: /\d/.test(password) },
  ];
}

function isPasswordValid(password: string) {
  return password.length >= 8 && /[a-z]/.test(password) && /[A-Z]/.test(password) && /\d/.test(password);
}

function emailValidationIssue(email: string): string | null {
  const trimmed = email.trim();
  if (!trimmed) return null;
  if (!trimmed.includes("@")) return "Email must contain an @ symbol.";
  const [local, domain] = trimmed.split("@");
  if (!local || !domain) return "Enter a complete email address.";
  if (!domain.includes(".")) return "Domain is missing a TLD (e.g. .com).";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) return "Enter a valid email address.";
  return null;
}

function phoneValidationIssue(phone: string): string | null {
  const trimmed = phone.trim();
  if (!trimmed) return null;
  const numericOnly = trimmed.replace(/[\s\-\(\)\.]+/g, "");
  if (numericOnly.length < 7) return "Number is too short.";
  if (numericOnly.length > 15) return "Number is too long.";
  if (!/^\+?\d+$/.test(numericOnly)) return "Use only digits, spaces, dashes, and an optional leading +.";
  return null;
}

interface MissingFieldInfo {
  key: string;
  label: string;
}

function collectMissingFields(
  form: CreateUserPayload,
  passwordConfirm: string,
  requiresSites: boolean,
): MissingFieldInfo[] {
  const missing: MissingFieldInfo[] = [];

  if (!form.full_name.trim()) missing.push({ key: "full_name", label: "Full name" });
  if (!form.email.trim() || emailValidationIssue(form.email)) missing.push({ key: "email", label: "Valid email" });
  if (!isPasswordValid(form.password)) missing.push({ key: "password", label: "Password requirements" });
  if (form.password !== passwordConfirm) missing.push({ key: "password_confirm", label: "Passwords match" });
  if (requiresSites && form.assigned_site_ids.length === 0) missing.push({ key: "locations", label: "At least one location" });

  return missing;
}

function roleTone(role: ManagedUserRole) {
  if (role === "Admin") return "user-role-admin";
  if (role === "AI_Engineer") return "user-role-ai";
  return "user-role-ops";
}

function statusLabel(status: ManagedUserStatus | string) {
  return humanizeIdentifier(status);
}

function statusTone(status: ManagedUserStatus) {
  if (status === "Available" || status === "In_Shift") return "user-status-available";
  if (status === "Busy" || status === "On_Break") return "user-status-busy";
  if (status === "Off_Duty" || status === "On_Leave") return "user-status-away";
  return "user-status-suspended";
}

export function UsersPage() {
  const { session } = useAuth();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [sites, setSites] = useState<LocationOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");
  const [form, setForm] = useState<CreateUserPayload>(EMPTY_FORM);
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [skipLocations, setSkipLocations] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<ManagedUser | null>(null);
  const [editingUserForm, setEditingUserForm] = useState<UpdateUserRolePayload>({});
  const [editingUserSubmitting, setEditingUserSubmitting] = useState(false);
  const [editingUserDeleteConfirm, setEditingUserDeleteConfirm] = useState(false);

  const currentEmail = session?.user.email.toLowerCase() ?? "";
  const siteById = useMemo(() => new Map(sites.map((site) => [site.id, site])), [sites]);
  const selectedLocations = useMemo(
    () => form.assigned_site_ids.map((siteId) => siteById.get(siteId) ?? { id: siteId, name: siteId }).filter(Boolean) as LocationOption[],
    [form.assigned_site_ids, siteById],
  );

  const recentLocationEntries = useMemo<RecentLocationEntry[]>(() => loadRecentLocationEntries(), [createOpen, editingUser]);

  async function refresh(signal?: AbortSignal) {
    setLoading(true);
    setError(null);
    try {
      const [userData, siteData] = await Promise.all([
        getUsers(signal),
        getLocationOptions({ includeArchived: false, limit: 100 }, signal),
      ]);
      setUsers(userData);
      setSites(siteData.locations);
    } catch (err) {
      if (!signal?.aborted) {
        setError(err instanceof Error ? err.message : "Unable to load users.");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      void refresh(controller.signal);
    }, 0);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, []);

  useEffect(() => {
    if (!createOpen) return undefined;

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setCreateOpen(false);
      }
    };

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [createOpen]);

  const filteredUsers = useMemo(() => {
    const terms = query
      .trim()
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean);

    return users.filter((user) => {
      if (roleFilter !== "all" && user.role !== roleFilter) return false;
      if (!terms.length) return true;
      const haystack = `${user.email} ${user.full_name} ${managedRoleLabel(user.role)}`.toLowerCase();
      return terms.every((term) => haystack.includes(term));
    });
  }, [query, roleFilter, users]);

  const roleCounts = useMemo(() => {
    const counts = new Map<ManagedUserRole, number>();
    USER_ROLES.forEach((role) => counts.set(role, 0));
    users.forEach((user) => counts.set(user.role, (counts.get(user.role) ?? 0) + 1));
    return counts;
  }, [users]);

  const adminCount = roleCounts.get("Admin") ?? 0;
  const operatorCount = roleCounts.get("Operator") ?? 0;
  const aiEngineerCount = roleCounts.get("AI_Engineer") ?? 0;

  const passwordReqs = passwordRequirements(form.password);
  const emailIssue = emailValidationIssue(form.email);
  const phoneIssue = phoneValidationIssue(form.contact_number ?? "");
  const passwordMismatch = form.password.length > 0 && passwordConfirm.length > 0 && form.password !== passwordConfirm;
  const requiresSites = form.role !== "AI_Engineer" && !(form.role === "Admin" && form.is_global_admin) && !skipLocations;
  const missingFields = collectMissingFields(form, passwordConfirm, requiresSites);
  const canSubmit = Boolean(
    form.email.trim() &&
    !emailIssue &&
    form.full_name.trim() &&
    isPasswordValid(form.password) &&
    form.password === passwordConfirm &&
    isManagedUserRole(form.role) &&
    (!requiresSites || form.assigned_site_ids.length > 0) &&
    !phoneIssue,
  );

  function roleDescription(role: ManagedUserRole) {
    if (role === "Admin") return "Full platform access. Can manage users, models, and system configuration.";
    if (role === "AI_Engineer") return "Read-only global access for model training and data analysis. Cannot perform operational actions.";
    return "Day-to-day operational access. Assigned to specific locations for monitoring and maintenance.";
  }

  function addAssignedLocation(location: LocationOption) {
    setSites((current) => (current.some((site) => site.id === location.id) ? current : [...current, location]));
    setForm((current) => {
      const selected = new Set(current.assigned_site_ids);
      selected.add(location.id);
      const nextIds = [...selected].sort();
      saveRecentLocationEntries([{ id: location.id, name: location.name ?? location.id } as LocationOption]);
      return { ...current, assigned_site_ids: nextIds };
    });
  }

  function removeAssignedLocation(locationId: string) {
    setForm((current) => ({
      ...current,
      assigned_site_ids: current.assigned_site_ids.filter((siteId) => siteId !== locationId),
    }));
  }

  function editingAddAssignedLocation(location: LocationOption) {
    setSites((current) => (current.some((site) => site.id === location.id) ? current : [...current, location]));
    setEditingUserForm((current) => {
      const prev = current.assigned_site_ids ?? [];
      const selected = new Set(prev);
      selected.add(location.id);
      const nextIds = [...selected].sort();
      saveRecentLocationEntries([{ id: location.id, name: location.name ?? location.id } as LocationOption]);
      return { ...current, assigned_site_ids: nextIds };
    });
  }

  function editingRemoveAssignedLocation(locationId: string) {
    setEditingUserForm((current) => ({
      ...current,
      assigned_site_ids: (current.assigned_site_ids ?? []).filter((siteId) => siteId !== locationId),
    }));
  }

  function scopeLabel(user: ManagedUser) {
    if (user.role === "AI_Engineer") return "Global read";
    if (user.role === "Admin" && user.is_global_admin) return "Global admin";
    if (!user.assigned_site_ids.length) return "No sites assigned";
    return user.assigned_site_ids.map((siteId) => displayLocationName(siteById.get(siteId)?.name, siteId)).join(", ");
  }

  function displayedStatus(user: ManagedUser): ManagedUserStatus {
    return user.email.toLowerCase() === currentEmail ? "Available" : user.status;
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;

    setSubmitting("create");
    setError(null);
    setMessage(null);
    try {
      const created = await createUser({
        email: form.email.trim().toLowerCase(),
        full_name: form.full_name.trim(),
        password: form.password,
        role: form.role,
        status: form.status,
        contact_number: form.contact_number?.trim() || null,
        assigned_site_ids: form.role === "AI_Engineer" || form.is_global_admin || skipLocations ? [] : form.assigned_site_ids,
        is_global_admin: form.role === "Admin" && form.is_global_admin,
      });
      setUsers((current) => [...current, created].sort((a, b) => a.email.localeCompare(b.email)));
      if (!skipLocations && form.assigned_site_ids.length > 0) {
        const createdLocations = form.assigned_site_ids
          .map((id) => siteById.get(id))
          .filter((loc): loc is LocationOption => Boolean(loc));
        saveRecentLocationEntries(createdLocations);
      }
      setForm(EMPTY_FORM);
      setPasswordConfirm("");
      setCreateOpen(false);
      setMessage(`${created.full_name} was created.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create user.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleDelete(user: ManagedUser) {
    setSubmitting(`delete-${user.id}`);
    setError(null);
    setMessage(null);
    try {
      await deleteUser(user.id);
      setUsers((current) => current.filter((item) => item.id !== user.id));
      setEditingUser(null);
      setEditingUserDeleteConfirm(false);
      setMessage(`${user.full_name} was removed.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete user.");
    } finally {
      setSubmitting(null);
    }
  }

  function openEditUser(user: ManagedUser) {
    setEditingUser(user);
    setEditingUserForm({
      role: user.role,
      status: user.status,
      contact_number: user.contact_number ?? "",
      is_global_admin: user.is_global_admin,
      assigned_site_ids: [...user.assigned_site_ids].sort(),
    });
    setEditingUserSubmitting(false);
    setEditingUserDeleteConfirm(false);
  }

  async function handleEditUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingUser) return;

    const resolvedRole = editingUserForm.role ?? editingUser.role;
    const resolvedIsGlobalAdmin = resolvedRole === "Admin" && (editingUserForm.is_global_admin ?? editingUser.is_global_admin);
    const resolvedAssignedSiteIds =
      resolvedRole === "AI_Engineer" || resolvedIsGlobalAdmin
        ? []
        : (editingUserForm.assigned_site_ids ?? editingUser.assigned_site_ids);

    const payload: UpdateUserRolePayload = {
      role: resolvedRole,
      status: editingUserForm.status,
      contact_number: editingUserForm.contact_number?.trim() || null,
      is_global_admin: resolvedIsGlobalAdmin,
      assigned_site_ids: resolvedAssignedSiteIds,
    };

    setEditingUserSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const updated = await updateUserRole(editingUser.id, payload);
      setUsers((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      if (resolvedAssignedSiteIds.length > 0) {
        const currentLocations = resolvedAssignedSiteIds
          .map((id) => siteById.get(id))
          .filter((loc): loc is LocationOption => Boolean(loc));
        saveRecentLocationEntries(currentLocations);
      }
      setEditingUser(null);
      setMessage(`${updated.full_name} was updated.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update user.");
    } finally {
      setEditingUserSubmitting(false);
    }
  }

  return (
    <main className="page users-page">
      <div className="page-head users-head">
        <div>
          <h1 className="page-title">User Management</h1>
          <p className="page-sub">Admin workspace for accounts, platform roles, and operational access.</p>
        </div>
        <div className="page-head-actions user-primary-actions">
          <button className="btn" type="button" onClick={() => refresh()} disabled={loading}>
            <Icon name="refresh" className={loading ? "spin" : undefined} />
            <span>{loading ? "Loading..." : "Refresh"}</span>
          </button>
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => {
              const adminSiteIds = session?.user.assignedSiteIds ?? [];
              setForm({
                ...EMPTY_FORM,
                assigned_site_ids: adminSiteIds,
              });
              setPasswordConfirm("");
              setSkipLocations(false);
              setCreateOpen(true);
            }}
          >
            <Icon name="plus" />
            <span>Create User</span>
          </button>
        </div>
      </div>

      {error && <div className="anomaly-error">{error}</div>}
      {message && <div className="models-success">{message}</div>}

      <section className="user-summary-grid">
        <div className="asset-summary-card">
          <span className="asset-summary-label">Total users</span>
          <b className="asset-summary-value">{users.length}</b>
          <span className="asset-summary-foot">{filteredUsers.length} shown</span>
        </div>
        <div className="asset-summary-card">
          <span className="asset-summary-label">Admins</span>
          <b className="asset-summary-value">{adminCount}</b>
          <span className="asset-summary-foot">Privileged accounts</span>
        </div>
        <div className="asset-summary-card">
          <span className="asset-summary-label">Operations</span>
          <b className="asset-summary-value">{operatorCount}</b>
          <span className="asset-summary-foot">Operator accounts</span>
        </div>
        <div className="asset-summary-card">
          <span className="asset-summary-label">AI engineering</span>
          <b className="asset-summary-value">{aiEngineerCount}</b>
          <span className="asset-summary-foot">Model operations access</span>
        </div>
      </section>

      <Card
        title="Directory"
        sub="Search accounts and update roles without leaving the table."
        icon="users"
        actions={
          <div className="asset-filter-row">
            <button className={roleFilter === "all" ? "is-selected" : ""} type="button" onClick={() => setRoleFilter("all")}>
              All
            </button>
            {USER_ROLES.map((role) => (
              <button key={role} className={roleFilter === role ? "is-selected" : ""} type="button" onClick={() => setRoleFilter(role)}>
                {managedRoleLabel(role)}
              </button>
            ))}
          </div>
        }
      >
        <div className="asset-toolbar">
          <div className="asset-toolbar-controls">
            <div className="asset-search">
              <Icon name="search" />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search users by name, email, or role" />
            </div>
            <span className="asset-search-help">{loading ? "Loading directory..." : `${filteredUsers.length} of ${users.length} users`}</span>
          </div>
        </div>

        <div className="user-table-wrap">
          <table className="user-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Status</th>
                <th>Scope</th>
                <th>Contact</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((user) => {
                const visibleStatus = displayedStatus(user);
                return (
                  <tr key={user.id}>
                    <td>
                      <div className="user-cell">
                        <span className="user-avatar">{userInitials(user)}</span>
                        <span>
                          <b>{user.full_name}</b>
                          <small>{user.email}</small>
                        </span>
                      </div>
                    </td>
                    <td>
                      <div className="user-role-cell">
                        <span className={`user-role-badge ${roleTone(user.role)}`}>{managedRoleLabel(user.role)}</span>
                      </div>
                    </td>
                    <td>
                      <span className="user-status-wrap">
                        <span className={`user-status-dot ${statusTone(visibleStatus)}`} aria-label={statusLabel(visibleStatus)} tabIndex={0} />
                        <span className="user-status-tip" role="tooltip">{statusLabel(visibleStatus)}</span>
                      </span>
                    </td>
                    <td>
                      <span className="user-scope-text">{scopeLabel(user)}</span>
                    </td>
                    <td>
                      <span className="user-contact">{user.contact_number || "Not set"}</span>
                    </td>
                    <td>
                      <button className="btn btn-small user-edit-btn" type="button" onClick={() => openEditUser(user)}>
                        <Icon name="settings" />
                        <span>Edit</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
              {!filteredUsers.length && (
                <tr>
                  <td colSpan={6}>
                    <div className="asset-empty">{loading ? "Loading users..." : "No users match the current filters."}</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {createOpen && (
        <div className="user-modal-backdrop" role="presentation" onMouseDown={() => setCreateOpen(false)}>
          <section className="user-modal" role="dialog" aria-modal="true" aria-labelledby="create-user-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="user-modal-head">
              <div>
                <h2 id="create-user-title">Create User</h2>
                <span>Set up a new account with role-based access and location assignments.</span>
              </div>
              <button className="icon-btn" type="button" aria-label="Close create user dialog" onClick={() => setCreateOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <form className="user-form user-modal-body" onSubmit={handleCreate}>
              {/* ── Missing required fields indicator ── */}
              {missingFields.length > 0 && (
                <div className="user-form-missing">
                  <Icon name="info" />
                  <span>
                    Complete the following:{" "}
                    {missingFields.map((field) => field.label).join(", ")}
                  </span>
                </div>
              )}

              {/* ── Identity ── */}
              <Field label="Full name">
                <input
                  className="input"
                  value={form.full_name}
                  onChange={(event) => setForm((current) => ({ ...current, full_name: event.target.value }))}
                  autoComplete="name"
                  placeholder="Jane Smith"
                  required
                />
              </Field>

              <Field label="Email">
                <input
                  className="input"
                  type="email"
                  value={form.email}
                  onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
                  autoComplete="email"
                  placeholder="jane@example.com"
                  required
                />
                {form.email.trim() && emailIssue && (
                  <span className="user-field-help">{emailIssue}</span>
                )}
                {form.email.trim() && !emailIssue && (
                  <span className="user-field-ok">Email format looks good.</span>
                )}
              </Field>

              <Field label="Contact number">
                <input
                  className="input"
                  value={form.contact_number ?? ""}
                  onChange={(event) => setForm((current) => ({ ...current, contact_number: event.target.value }))}
                  autoComplete="tel"
                  placeholder="+1 555 123 4567"
                />
                {form.contact_number?.trim() && phoneIssue && (
                  <span className="user-field-help">{phoneIssue}</span>
                )}
              </Field>

              {/* ── Permissions & Scope ── */}
              <Field label="Role">
                <Select
                  value={form.role}
                  onChange={(role) =>
                    setForm((current) => ({
                      ...current,
                      role,
                      assigned_site_ids: role === "AI_Engineer" ? [] : current.assigned_site_ids,
                      is_global_admin: role === "Admin" ? current.is_global_admin : false,
                    }))
                  }
                  options={USER_ROLES.map((role) => ({ value: role, label: managedRoleLabel(role) }))}
                />
                <span className="user-role-hint">{roleDescription(form.role)}</span>
              </Field>

              <Field label="Work status">
                <Select
                  value={form.status}
                  onChange={(status) => setForm((current) => ({ ...current, status }))}
                  options={USER_STATUSES.map((status) => ({ value: status, label: statusLabel(status) }))}
                />
              </Field>

              {form.role === "Admin" && session?.user.isGlobalAdmin && (
                <label className="user-check-row">
                  <input
                    type="checkbox"
                    checked={form.is_global_admin}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        is_global_admin: event.target.checked,
                        assigned_site_ids: event.target.checked ? [] : current.assigned_site_ids,
                      }))
                    }
                  />
                  <span>
                    <b>Global admin</b>
                    <small>City-level access to all properties and user management.</small>
                  </span>
                </label>
              )}

              {form.role === "AI_Engineer" ? (
                <div className="user-scope-note">
                  AI Engineers receive global read access for model training, but remain functionally restricted from operational actions.
                </div>
              ) : form.is_global_admin ? null : (
                <>
                  {!skipLocations && (
                    <Field label="Assigned locations">
                      <UserLocationPicker
                        selectedIds={form.assigned_site_ids}
                        selectedLocations={selectedLocations}
                        siteById={siteById}
                        onAdd={addAssignedLocation}
                        onRemove={removeAssignedLocation}
                        recentLocationEntries={recentLocationEntries}
                      />
                    </Field>
                  )}
                  <label className="user-check-row user-check-row-skip">
                    <input
                      type="checkbox"
                      checked={skipLocations}
                      onChange={(event) => {
                        setSkipLocations(event.target.checked);
                        if (event.target.checked) {
                          setForm((current) => ({ ...current, assigned_site_ids: [] }));
                        }
                      }}
                    />
                    <span>
                      <b>Assign locations later</b>
                      <small>Skip location assignment during creation. You can assign locations from the user table afterward.</small>
                    </span>
                  </label>
                  {skipLocations && (
                    <div className="user-scope-note user-scope-note-warn">
                      This user will have no data access until locations are assigned. Use the scope column in the table to add locations after creation.
                    </div>
                  )}
                </>
              )}

              {/* ── Security ── */}
              <Field label="Password">
                <input
                  className="input"
                  type="password"
                  value={form.password}
                  onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
                  autoComplete="new-password"
                  placeholder="Enter a strong password"
                  required
                />
                {form.password.length > 0 && (
                  <div className="user-password-checklist">
                    {passwordReqs.map((req) => (
                      <span key={req.label} className={`user-password-req ${req.met ? "met" : ""}`}>
                        <Icon name={req.met ? "check" : "dot"} />
                        {req.label}
                      </span>
                    ))}
                  </div>
                )}
              </Field>

              <Field label="Confirm password">
                <input
                  className="input"
                  type="password"
                  value={passwordConfirm}
                  onChange={(event) => setPasswordConfirm(event.target.value)}
                  autoComplete="new-password"
                  placeholder="Re-enter the password"
                  required
                />
                {passwordMismatch && (
                  <span className="user-field-help">Passwords do not match.</span>
                )}
                {form.password.length > 0 && passwordConfirm.length > 0 && !passwordMismatch && (
                  <span className="user-field-ok">Passwords match.</span>
                )}
              </Field>

              {/* ── Footer ── */}
              <div className="user-modal-foot">
                <div className="user-submit-summary">
                  {missingFields.length > 0 ? (
                    <span className="user-submit-hint">
                      {missingFields.length} field{missingFields.length !== 1 ? "s" : ""} remaining
                    </span>
                  ) : (
                    <span className="user-submit-ready">Ready to create {managedRoleLabel(form.role).toLowerCase()} account</span>
                  )}
                </div>
                <div className="user-modal-foot-actions">
                  <button className="btn" type="button" onClick={() => setCreateOpen(false)} disabled={submitting === "create"}>
                    Cancel
                  </button>
                  <button className="btn btn-primary" type="submit" disabled={!canSubmit || submitting === "create"}>
                    <Icon name={submitting === "create" ? "refresh" : "plus"} className={submitting === "create" ? "spin" : undefined} />
                    <span>{submitting === "create" ? "Creating..." : "Create User"}</span>
                  </button>
                </div>
              </div>
            </form>
          </section>
        </div>
      )}

      {editingUser && (
        <div className="user-modal-backdrop" role="presentation" onMouseDown={() => setEditingUser(null)}>
          <section className="user-modal" role="dialog" aria-modal="true" aria-labelledby="edit-user-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="user-modal-head">
              <div>
                <h2 id="edit-user-title">Edit User</h2>
                <span>
                  {editingUser.full_name} &middot; {editingUser.email}
                </span>
              </div>
              <button className="icon-btn" type="button" aria-label="Close edit user dialog" onClick={() => setEditingUser(null)}>
                <Icon name="x" />
              </button>
            </div>
            <form className="user-form user-modal-body" onSubmit={handleEditUser}>
              <Field label="Full name">
                <input
                  className="input input-disabled"
                  value={editingUser.full_name}
                  disabled
                  readOnly
                />
              </Field>

              <Field label="Email">
                <input
                  className="input input-disabled"
                  value={editingUser.email}
                  disabled
                  readOnly
                />
              </Field>

              <Field label="Role">
                <Select
                  value={editingUserForm.role ?? editingUser.role}
                  onChange={(role) =>
                    setEditingUserForm((current) => ({
                      ...current,
                      role,
                      is_global_admin: role === "Admin" ? current.is_global_admin : false,
                      assigned_site_ids: role === "AI_Engineer" ? [] : current.assigned_site_ids,
                    }))
                  }
                  options={USER_ROLES.map((role) => ({ value: role, label: managedRoleLabel(role) }))}
                />
                <span className="user-role-hint">{roleDescription(editingUserForm.role ?? editingUser.role)}</span>
              </Field>

              <Field label="Work status">
                <Select
                  value={editingUserForm.status ?? editingUser.status}
                  onChange={(status) =>
                    setEditingUserForm((current) => ({ ...current, status }))
                  }
                  options={USER_STATUSES.map((status) => ({ value: status, label: statusLabel(status) }))}
                />
              </Field>

              <Field label="Contact number">
                <input
                  className="input"
                  value={editingUserForm.contact_number ?? ""}
                  onChange={(event) =>
                    setEditingUserForm((current) => ({ ...current, contact_number: event.target.value }))
                  }
                  autoComplete="tel"
                  placeholder="+1 555 123 4567"
                />
              </Field>

              {/* ── Location assignments ── */}
              {(editingUserForm.role ?? editingUser.role) !== "AI_Engineer" && !(editingUserForm.is_global_admin ?? editingUser.is_global_admin) && (
                <Field label="Assigned locations">
                  <UserLocationPicker
                    selectedIds={editingUserForm.assigned_site_ids ?? editingUser.assigned_site_ids}
                    selectedLocations={(editingUserForm.assigned_site_ids ?? editingUser.assigned_site_ids)
                      .map((siteId) => siteById.get(siteId) ?? { id: siteId, name: siteId })
                      .filter(Boolean) as LocationOption[]}
                    siteById={siteById}
                    onAdd={editingAddAssignedLocation}
                    onRemove={editingRemoveAssignedLocation}
                    recentLocationEntries={recentLocationEntries}
                  />
                </Field>
              )}

              {(editingUserForm.role ?? editingUser.role) === "Admin" && session?.user.isGlobalAdmin && (
                <label className="user-check-row">
                  <input
                    type="checkbox"
                    checked={editingUserForm.is_global_admin ?? editingUser.is_global_admin}
                    onChange={(event) =>
                      setEditingUserForm((current) => ({
                        ...current,
                        is_global_admin: event.target.checked,
                        assigned_site_ids: event.target.checked ? [] : current.assigned_site_ids,
                      }))
                    }
                  />
                  <span>
                    <b>Global admin</b>
                    <small>City-level access to all properties and user management.</small>
                  </span>
                </label>
              )}

              {/* ── Danger zone ── */}
              <div className="user-delete-zone">
                {(() => {
                  const isEditingSelf = editingUser.email.toLowerCase() === currentEmail;
                  const isDeleting = submitting === `delete-${editingUser.id}`;
                  if (editingUserDeleteConfirm) {
                    return (
                      <div className="user-delete-confirm">
                        <span>Permanently delete <b>{editingUser.full_name}</b>? This cannot be undone.</span>
                        <div className="user-delete-confirm-actions">
                          <button
                            className="btn btn-small"
                            type="button"
                            onClick={() => setEditingUserDeleteConfirm(false)}
                            disabled={isDeleting}
                          >
                            Cancel
                          </button>
                          <button
                            className="btn btn-small user-danger"
                            type="button"
                            onClick={() => handleDelete(editingUser)}
                            disabled={isDeleting}
                          >
                            <Icon name={isDeleting ? "refresh" : "x"} className={isDeleting ? "spin" : undefined} />
                            <span>{isDeleting ? "Deleting..." : "Delete permanently"}</span>
                          </button>
                        </div>
                      </div>
                    );
                  }
                  return (
                    <button
                      className="btn btn-small user-delete-btn"
                      type="button"
                      onClick={() => setEditingUserDeleteConfirm(true)}
                      disabled={isEditingSelf}
                    >
                      <Icon name="x" />
                      <span>{isEditingSelf ? "Cannot delete yourself" : "Delete User"}</span>
                    </button>
                  );
                })()}
              </div>

              <div className="user-modal-foot">
                <div className="user-submit-summary">
                  <span className="user-submit-hint">
                    {(editingUserForm.role ?? editingUser.role) === "AI_Engineer"
                      ? "AI Engineers have global read-only access."
                      : (editingUserForm.is_global_admin ?? editingUser.is_global_admin)
                        ? "Global admin — access to all locations."
                        : (() => {
                            const count = (editingUserForm.assigned_site_ids ?? editingUser.assigned_site_ids).length;
                            return count > 0
                              ? `${count} location${count !== 1 ? "s" : ""} assigned`
                              : "No locations assigned";
                          })()}
                  </span>
                </div>
                <div className="user-modal-foot-actions">
                  <button className="btn" type="button" onClick={() => setEditingUser(null)} disabled={editingUserSubmitting}>
                    Cancel
                  </button>
                  <button className="btn btn-primary" type="submit" disabled={editingUserSubmitting}>
                    <Icon name={editingUserSubmitting ? "refresh" : "check"} className={editingUserSubmitting ? "spin" : undefined} />
                    <span>{editingUserSubmitting ? "Saving..." : "Save Changes"}</span>
                  </button>
                </div>
              </div>
            </form>
          </section>
        </div>
      )}
    </main>
  );
}
