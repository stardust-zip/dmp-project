"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Icon } from "@/components/common/icons";
import { Card, Field, Select } from "@/components/common/primitives";
import { displayLocationName, humanizeIdentifier } from "@/lib/format";
import { getLocationOptions, type LocationOption } from "@/lib/models-api";
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

function userInitials(user: ManagedUser) {
  const source = user.full_name || user.email;
  return source
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
}

function passwordIssue(password: string) {
  if (password.length < 8) return "Use at least 8 characters.";
  if (!/[a-z]/.test(password) || !/[A-Z]/.test(password) || !/\d/.test(password)) {
    return "Use uppercase, lowercase, and a number.";
  }
  return null;
}

function roleTone(role: ManagedUserRole) {
  if (role === "Admin") return "user-role-admin";
  if (role === "AI_Engineer") return "user-role-ai";
  return "user-role-ops";
}

function locationTypeLabel(location: LocationOption) {
  return location.location_type ? humanizeIdentifier(location.location_type) : "Location";
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
  const [createOpen, setCreateOpen] = useState(false);
  const [locationQuery, setLocationQuery] = useState("");
  const [locationResults, setLocationResults] = useState<LocationOption[]>([]);
  const [locationSearchLoading, setLocationSearchLoading] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const currentEmail = session?.user.email.toLowerCase() ?? "";
  const siteById = useMemo(() => new Map(sites.map((site) => [site.id, site])), [sites]);
  const selectedLocations = useMemo(
    () => form.assigned_site_ids.map((siteId) => siteById.get(siteId) ?? { id: siteId, name: siteId }).filter(Boolean) as LocationOption[],
    [form.assigned_site_ids, siteById],
  );

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

  useEffect(() => {
    const queryText = locationQuery.trim();

    if (!createOpen || form.role === "AI_Engineer" || form.is_global_admin || !queryText) {
      const timeout = window.setTimeout(() => {
        setLocationResults([]);
        setLocationSearchLoading(false);
      }, 0);
      return () => window.clearTimeout(timeout);
    }

    if (queryText.length < 2) {
      const timeout = window.setTimeout(() => {
        setLocationResults([]);
        setLocationSearchLoading(false);
      }, 0);
      return () => window.clearTimeout(timeout);
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      setLocationSearchLoading(true);
      try {
        const data = await getLocationOptions(
          {
            q: queryText,
            includeArchived: false,
            limit: 25,
          },
          controller.signal,
        );
        setLocationResults(data.locations);
      } catch {
        if (!controller.signal.aborted) setLocationResults([]);
      } finally {
        if (!controller.signal.aborted) setLocationSearchLoading(false);
      }
    }, 180);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [createOpen, form.is_global_admin, form.role, locationQuery]);

  useEffect(() => {
    if (createOpen) return undefined;

    const timeout = window.setTimeout(() => {
      setLocationQuery("");
      setLocationResults([]);
      setLocationSearchLoading(false);
    }, 0);

    return () => window.clearTimeout(timeout);
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
  const issue = passwordIssue(form.password);
  const requiresSites = form.role !== "AI_Engineer" && !(form.role === "Admin" && form.is_global_admin);
  const canSubmit = Boolean(
    form.email.trim() &&
    form.full_name.trim() &&
    form.password &&
    !issue &&
    isManagedUserRole(form.role) &&
    (!requiresSites || form.assigned_site_ids.length > 0),
  );

  function addAssignedLocation(location: LocationOption) {
    setSites((current) => (current.some((site) => site.id === location.id) ? current : [...current, location]));
    setForm((current) => {
      const selected = new Set(current.assigned_site_ids);
      selected.add(location.id);
      return { ...current, assigned_site_ids: [...selected].sort() };
    });
    setLocationQuery("");
  }

  function removeAssignedLocation(locationId: string) {
    setForm((current) => ({
      ...current,
      assigned_site_ids: current.assigned_site_ids.filter((siteId) => siteId !== locationId),
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
        assigned_site_ids: form.role === "AI_Engineer" || form.is_global_admin ? [] : form.assigned_site_ids,
        is_global_admin: form.role === "Admin" && form.is_global_admin,
      });
      setUsers((current) => [...current, created].sort((a, b) => a.email.localeCompare(b.email)));
      setForm(EMPTY_FORM);
      setCreateOpen(false);
      setMessage(`${created.full_name} was created.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create user.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleRoleChange(user: ManagedUser, role: ManagedUserRole) {
    if (user.role === role) return;

    setSubmitting(`role-${user.id}`);
    setError(null);
    setMessage(null);
    try {
      const updated = await updateUserRole(user.id, { role });
      setUsers((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setMessage(`${updated.full_name} is now ${managedRoleLabel(updated.role)}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update role.");
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
      setConfirmDeleteId(null);
      setMessage(`${user.full_name} was removed.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete user.");
    } finally {
      setSubmitting(null);
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
              setForm(EMPTY_FORM);
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
                const isSelf = user.email.toLowerCase() === currentEmail;
                const visibleStatus = displayedStatus(user);
                const deleting = submitting === `delete-${user.id}`;
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
                      {confirmDeleteId === user.id ? (
                        <div className="user-action-confirm">
                          <button className="btn btn-small btn-ghost" type="button" onClick={() => setConfirmDeleteId(null)} disabled={deleting}>
                            Cancel
                          </button>
                          <button className="btn btn-small user-danger" type="button" onClick={() => handleDelete(user)} disabled={deleting}>
                            <Icon name={deleting ? "refresh" : "x"} className={deleting ? "spin" : undefined} />
                            <span>{deleting ? "Removing" : "Confirm"}</span>
                          </button>
                        </div>
                      ) : (
                        <button className="btn btn-small user-danger" type="button" onClick={() => setConfirmDeleteId(user.id)} disabled={isSelf}>
                          <Icon name="x" />
                          <span>{isSelf ? "Current user" : "Remove"}</span>
                        </button>
                      )}
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
                <span>New accounts receive role-scoped access immediately.</span>
              </div>
              <button className="icon-btn" type="button" aria-label="Close create user dialog" onClick={() => setCreateOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <form className="user-form user-modal-body" onSubmit={handleCreate}>
              <Field label="Full name">
                <input
                  className="input"
                  value={form.full_name}
                  onChange={(event) => setForm((current) => ({ ...current, full_name: event.target.value }))}
                  autoComplete="name"
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
                  required
                />
              </Field>
              <Field label="Contact number">
                <input
                  className="input"
                  value={form.contact_number ?? ""}
                  onChange={(event) => setForm((current) => ({ ...current, contact_number: event.target.value }))}
                  autoComplete="tel"
                  placeholder="+1 555 123 4567"
                />
              </Field>
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
              ) : !form.is_global_admin ? (
                <Field label="Assigned locations">
                  <div className="user-location-picker">
                    <div className="user-location-search">
                      <Icon name="search" />
                      <input value={locationQuery} onChange={(event) => setLocationQuery(event.target.value)} placeholder="Search building, site, or location ID" />
                    </div>
                    <div className="user-location-results">
                      {locationSearchLoading ? (
                        <div className="user-location-empty">Searching locations...</div>
                      ) : (
                        locationResults
                          .filter((location) => !form.assigned_site_ids.includes(location.id))
                          .slice(0, 8)
                          .map((location) => (
                            <button key={location.id} className="user-location-result" type="button" onClick={() => addAssignedLocation(location)}>
                              <span>
                                <b>{displayLocationName(location.name, location.id)}</b>
                                <small>
                                  {locationTypeLabel(location)}
                                  {location.parent_id ? ` in ${displayLocationName(siteById.get(location.parent_id)?.name, location.parent_id)}` : ""}
                                </small>
                              </span>
                              <Icon name="plus" />
                            </button>
                          ))
                      )}
                      {!locationSearchLoading && locationQuery.trim().length < 2 && (
                        <div className="user-location-empty">Type at least 2 characters to search locations.</div>
                      )}
                      {!locationSearchLoading && locationQuery.trim().length >= 2 && !locationResults.filter((location) => !form.assigned_site_ids.includes(location.id)).length && (
                        <div className="user-location-empty">No matching unassigned locations.</div>
                      )}
                    </div>
                    <div className="user-location-chips">
                      {selectedLocations.map((location) => (
                        <button key={location.id} className="user-location-chip" type="button" onClick={() => removeAssignedLocation(location.id)} title="Remove location">
                          <span>{displayLocationName(location.name, location.id)}</span>
                          <Icon name="x" />
                        </button>
                      ))}
                      {!selectedLocations.length && <span className="user-location-placeholder">Assign one or more locations.</span>}
                    </div>
                  </div>
                </Field>
              ) : null}
              <Field label="Temporary password">
                <input
                  className="input"
                  type="password"
                  value={form.password}
                  onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
                  autoComplete="new-password"
                  required
                />
                {form.password && issue && <span className="user-field-help">{issue}</span>}
              </Field>
              <div className="user-modal-foot">
                <button className="btn" type="button" onClick={() => setCreateOpen(false)} disabled={submitting === "create"}>
                  Cancel
                </button>
                <button className="btn btn-primary" type="submit" disabled={!canSubmit || submitting === "create"}>
                  <Icon name={submitting === "create" ? "refresh" : "plus"} className={submitting === "create" ? "spin" : undefined} />
                  <span>{submitting === "create" ? "Creating..." : "Create User"}</span>
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </main>
  );
}
