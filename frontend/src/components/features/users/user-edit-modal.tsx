"use client";

import { useMemo, useState, type FormEvent } from "react";
import { Icon } from "@/components/common/icons";
import { Field, Select } from "@/components/common/primitives";
import { UserLocationPicker } from "@/components/features/users/user-location-picker";
import { humanizeIdentifier } from "@/lib/format";
import { type LocationOption } from "@/lib/models-api";
import {
  USER_ROLES,
  USER_STATUSES,
  deleteUser,
  managedRoleLabel,
  updateUserRole,
  type ManagedUser,
  type ManagedUserRole,
  type UpdateUserRolePayload,
} from "@/lib/users-api";

interface RecentLocationEntry {
  id: string;
  name: string;
  parent_id?: string | null;
  location_type?: string | null;
}

export interface UserEditModalProps {
  user: ManagedUser;
  currentEmail: string;
  currentUserIsGlobalAdmin: boolean;
  locations: LocationOption[];
  recentLocationEntries?: RecentLocationEntry[];
  allowDelete?: boolean;
  lockRole?: ManagedUserRole;
  onClose: () => void;
  onSaved: (user: ManagedUser) => void;
  onDeleted?: (user: ManagedUser) => void;
  onLocationsDiscovered?: (locations: LocationOption[]) => void;
}

function roleDescription(role: ManagedUserRole) {
  if (role === "Admin") return "Manage users and assets. Enable global admin below for cross-site access, or assign specific locations for site-scoped management.";
  if (role === "AI_Engineer") return "Read-only global access for model training and data analysis. Cannot perform operational actions.";
  return "Day-to-day operational access. Assigned to specific locations for monitoring and maintenance.";
}

function statusLabel(status: string) {
  return humanizeIdentifier(status);
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

function rootSiteId(location: LocationOption) {
  return location.location_type === "site" ? location.id : location.parent_id ?? location.id;
}

export function UserEditModal({
  user,
  currentEmail,
  currentUserIsGlobalAdmin,
  locations,
  recentLocationEntries = [],
  allowDelete = true,
  lockRole,
  onClose,
  onSaved,
  onDeleted,
  onLocationsDiscovered,
}: UserEditModalProps) {
  const [form, setForm] = useState<UpdateUserRolePayload>({
    full_name: user.full_name,
    email: user.email,
    role: lockRole ?? user.role,
    status: user.status,
    contact_number: user.contact_number ?? "",
    is_global_admin: user.is_global_admin,
    assigned_site_ids: [...user.assigned_site_ids].sort(),
  });
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const siteById = useMemo(() => new Map(locations.map((location) => [location.id, location])), [locations]);
  const resolvedRole = lockRole ?? form.role ?? user.role;
  const resolvedIsGlobal = resolvedRole === "Admin" && (form.is_global_admin ?? user.is_global_admin);
  const assignedLocationIds = form.assigned_site_ids ?? user.assigned_site_ids;
  const requiresAssignedLocations = resolvedRole === "Operator" || (resolvedRole === "Admin" && !resolvedIsGlobal);
  const assignmentIssue = requiresAssignedLocations && assignedLocationIds.length === 0
    ? "Assign at least one location before saving this user."
    : null;
  const selectedLocations = assignedLocationIds
    .map((locationId) => siteById.get(locationId) ?? { id: locationId, name: locationId })
    .filter(Boolean) as LocationOption[];
  const emailIssue = emailValidationIssue(form.email ?? user.email);

  function addAssignedLocation(location: LocationOption) {
    onLocationsDiscovered?.([location]);
    setForm((current) => {
      const previousIds = current.assigned_site_ids ?? user.assigned_site_ids;
      if (resolvedRole === "Operator") {
        const selectedSiteId = previousIds
          .map((locationId) => siteById.get(locationId) ?? { id: locationId, name: locationId })
          .map((item) => rootSiteId(item as LocationOption))
          .find(Boolean);
        const nextSiteId = rootSiteId(location);
        if (selectedSiteId && nextSiteId !== selectedSiteId) return current;
      }
      const selected = new Set(previousIds);
      selected.add(location.id);
      return { ...current, assigned_site_ids: [...selected].sort() };
    });
  }

  function removeAssignedLocation(locationId: string) {
    setForm((current) => ({
      ...current,
      assigned_site_ids: (current.assigned_site_ids ?? user.assigned_site_ids).filter((id) => id !== locationId),
    }));
  }

  function replaceAssignedLocation(location: LocationOption) {
    onLocationsDiscovered?.([location]);
    setForm((current) => ({ ...current, assigned_site_ids: [location.id] }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (emailIssue || assignmentIssue) return;

    const resolvedAssignedSiteIds =
      (resolvedRole === "Operator" || (resolvedRole === "Admin" && !resolvedIsGlobal))
        ? assignedLocationIds
        : [];

    const payload: UpdateUserRolePayload = {
      full_name: form.full_name?.trim() || undefined,
      email: form.email?.trim().toLowerCase() || undefined,
      role: resolvedRole,
      status: form.status,
      contact_number: form.contact_number?.trim() || null,
      is_global_admin: resolvedIsGlobal,
      assigned_site_ids: resolvedAssignedSiteIds,
    };

    setSubmitting(true);
    setError(null);
    try {
      const updated = await updateUserRole(user.id, payload);
      onLocationsDiscovered?.(
        resolvedAssignedSiteIds
          .map((locationId) => siteById.get(locationId))
          .filter((location): location is LocationOption => Boolean(location)),
      );
      onSaved(updated);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update user.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete() {
    setDeleting(true);
    setError(null);
    try {
      await deleteUser(user.id);
      onDeleted?.(user);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete user.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="user-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="user-modal" role="dialog" aria-modal="true" aria-labelledby="edit-user-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="user-modal-head">
          <div>
            <h2 id="edit-user-title">Edit User</h2>
            <span>{user.full_name} &middot; {user.email}</span>
          </div>
          <button className="icon-btn" type="button" aria-label="Close edit user dialog" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        <form className="user-form user-modal-body" onSubmit={handleSubmit}>
          <Field label="Full name">
            <input className="input" value={form.full_name ?? user.full_name} onChange={(event) => setForm((current) => ({ ...current, full_name: event.target.value }))} autoComplete="name" placeholder="Jane Smith" required />
          </Field>

          <Field label="Email">
            <input className="input" type="email" value={form.email ?? user.email} onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))} autoComplete="email" placeholder="jane@example.com" required />
            {(form.email ?? user.email).trim() && emailIssue && <span className="user-field-help">{emailIssue}</span>}
            {(form.email ?? user.email).trim() && !emailIssue && <span className="user-field-ok">Email format accepted.</span>}
          </Field>

          <Field label="Role">
            {lockRole ? (
              <input className="input" value={managedRoleLabel(lockRole)} disabled />
            ) : (
              <Select
                value={resolvedRole}
                onChange={(role) => setForm((current) => ({
                  ...current,
                  role,
                  is_global_admin: role === "Admin" ? current.is_global_admin : false,
                  assigned_site_ids: role === "AI_Engineer" ? [] : current.assigned_site_ids,
                }))}
                options={USER_ROLES.map((role) => ({ value: role, label: managedRoleLabel(role) }))}
              />
            )}
            <span className="user-role-hint">{roleDescription(resolvedRole)}</span>
          </Field>

          <Field label="Work status">
            <Select value={form.status ?? user.status} onChange={(status) => setForm((current) => ({ ...current, status }))} options={USER_STATUSES.map((status) => ({ value: status, label: statusLabel(status) }))} />
          </Field>

          <Field label="Contact number">
            <input className="input" value={form.contact_number ?? ""} onChange={(event) => setForm((current) => ({ ...current, contact_number: event.target.value }))} autoComplete="tel" placeholder="+1 555 123 4567" />
          </Field>

          {resolvedRole === "Admin" && currentUserIsGlobalAdmin && (
            <label className="user-check-row">
              <input
                type="checkbox"
                checked={form.is_global_admin ?? user.is_global_admin}
                onChange={(event) => setForm((current) => ({
                  ...current,
                  is_global_admin: event.target.checked,
                  assigned_site_ids: event.target.checked ? [] : current.assigned_site_ids,
                }))}
              />
              <span>
                <b>Global admin</b>
                <small>Access to all locations, users, and system configuration across every site.</small>
              </span>
            </label>
          )}

          {resolvedRole === "AI_Engineer" || (resolvedRole === "Admin" && resolvedIsGlobal) ? (
            <div className="user-scope-note">
              {resolvedRole === "AI_Engineer" ? "AI Engineers have global read-only access." : "Global admins have access to all locations."}
            </div>
          ) : (
            <Field label="Assigned locations">
              <UserLocationPicker
                selectedIds={assignedLocationIds}
                selectedLocations={selectedLocations}
                siteById={siteById}
                onAdd={addAssignedLocation}
                onRemove={removeAssignedLocation}
                onReplace={replaceAssignedLocation}
                recentLocationEntries={recentLocationEntries}
                enforceSingleSite={resolvedRole === "Operator"}
              />
              {resolvedRole === "Operator" && <span className="user-role-hint">Select one site, or multiple buildings from the same site.</span>}
              {assignmentIssue && <span className="user-field-help">{assignmentIssue}</span>}
            </Field>
          )}

          {allowDelete && (
            <div className="user-delete-zone">
              {deleteConfirm ? (
                <div className="user-delete-confirm">
                  <span>Permanently delete <b>{user.full_name}</b>? This cannot be undone.</span>
                  <div className="user-delete-confirm-actions">
                    <button className="btn btn-small" type="button" onClick={() => setDeleteConfirm(false)} disabled={deleting}>Cancel</button>
                    <button className="btn btn-small user-danger" type="button" onClick={handleDelete} disabled={deleting}>
                      <Icon name={deleting ? "refresh" : "x"} className={deleting ? "spin" : undefined} />
                      <span>{deleting ? "Deleting..." : "Delete permanently"}</span>
                    </button>
                  </div>
                </div>
              ) : (
                <button className="btn btn-small user-delete-btn" type="button" onClick={() => setDeleteConfirm(true)} disabled={user.email.toLowerCase() === currentEmail}>
                  <Icon name="x" />
                  <span>{user.email.toLowerCase() === currentEmail ? "Cannot delete yourself" : "Delete User"}</span>
                </button>
              )}
            </div>
          )}

          {error && (
            <div className="user-form-error" role="alert">
              <Icon name="info" />
              <span>{error}</span>
            </div>
          )}
          <div className="user-modal-foot">
            <div className="user-submit-summary">
              <span className="user-submit-hint">
                {resolvedRole === "Admin" && resolvedIsGlobal
                  ? "Global admin - all locations."
                  : resolvedRole === "AI_Engineer"
                    ? "Global read-only access."
                    : assignedLocationIds.length > 0
                      ? `${assignedLocationIds.length} location${assignedLocationIds.length !== 1 ? "s" : ""} assigned`
                      : "No locations assigned"}
              </span>
            </div>
            <div className="user-modal-foot-actions">
              <button className="btn" type="button" onClick={onClose} disabled={submitting}>Cancel</button>
              <button className="btn btn-primary" type="submit" disabled={submitting || Boolean(emailIssue) || Boolean(assignmentIssue)}>
                <Icon name={submitting ? "refresh" : "check"} className={submitting ? "spin" : undefined} />
                <span>{submitting ? "Saving..." : "Save Changes"}</span>
              </button>
            </div>
          </div>
        </form>
      </section>
    </div>
  );
}
