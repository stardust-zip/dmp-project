import { authHeaders, roleLabel } from "@/lib/auth-api";
import type { AuthRole } from "@/types/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/backend";

export const USER_ROLES = ["Admin", "AI_Engineer", "Operator"] as const;
export const USER_STATUSES = ["Available", "In_Shift", "Busy", "On_Break", "Off_Duty", "On_Leave", "Suspended"] as const;

export type ManagedUserRole = (typeof USER_ROLES)[number];
export type ManagedUserStatus = (typeof USER_STATUSES)[number];

export interface ManagedUser {
  id: string;
  email: string;
  full_name: string;
  role: ManagedUserRole;
  status: ManagedUserStatus;
  contact_number?: string | null;
  assigned_site_ids: string[];
  is_global_admin: boolean;
}

export interface CreateUserPayload {
  email: string;
  full_name: string;
  password: string;
  role: ManagedUserRole;
  status: ManagedUserStatus;
  contact_number?: string | null;
  assigned_site_ids: string[];
  is_global_admin: boolean;
}

export interface UpdateUserRolePayload {
  role?: ManagedUserRole;
  status?: ManagedUserStatus;
  contact_number?: string | null;
  assigned_site_ids?: string[];
  is_global_admin?: boolean;
}

type ApiErrorPayload = {
  detail?: unknown;
  error?: unknown;
  message?: unknown;
};

export function isManagedUserRole(role: AuthRole | string | undefined): role is ManagedUserRole {
  return USER_ROLES.includes(role as ManagedUserRole);
}

export function managedRoleLabel(role: ManagedUserRole | AuthRole | string | undefined) {
  return roleLabel(role);
}

function formatApiDetail(detail: unknown): string | null {
  if (!detail) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const loc = "loc" in item && Array.isArray(item.loc) ? item.loc.join(".") : null;
          return loc ? `${loc}: ${String(item.msg)}` : String(item.msg);
        }
        return null;
      })
      .filter(Boolean)
      .join(" ");
  }
  return null;
}

async function apiErrorMessage(response: Response): Promise<string> {
  if (response.status === 401 || response.status === 403) {
    return "Your current session does not have permission to manage users.";
  }
  if (response.status === 502) {
    return "Backend is unavailable. Confirm the dmp_backend container is running and healthy, then refresh this page.";
  }

  const data = (await response.json().catch(() => null)) as ApiErrorPayload | null;
  const detail = formatApiDetail(data?.detail);
  const error = typeof data?.error === "string" ? data.error : null;
  const message = typeof data?.message === "string" ? data.message : null;
  return detail ?? error ?? message ?? `API request failed: ${response.status}`;
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...authHeaders(),
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    throw new Error(await apiErrorMessage(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export function getUsers(signal?: AbortSignal) {
  return apiJson<ManagedUser[]>("/api/v1/users", { signal });
}

export function createUser(payload: CreateUserPayload, signal?: AbortSignal) {
  return apiJson<ManagedUser>("/api/v1/users", {
    method: "POST",
    signal,
    body: JSON.stringify(payload),
  });
}

export function updateUserRole(userId: string, payload: UpdateUserRolePayload, signal?: AbortSignal) {
  return apiJson<ManagedUser>(`/api/v1/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    signal,
    body: JSON.stringify(payload),
  });
}

export function deleteUser(userId: string, signal?: AbortSignal) {
  return apiJson<void>(`/api/v1/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
    signal,
  });
}
