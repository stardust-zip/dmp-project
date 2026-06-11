import type { AuthSession, JwtPayload, LoginCredentials, LoginResponse } from "@/types/auth";
import type { AuthRole } from "@/types/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/backend";
const SESSION_STORAGE_KEY = "dmp.auth.session";

const USER_NAMES: Record<string, string> = {
  "admin@dmp.com": "Demo Admin",
  "operator@dmp.com": "Demo Operator",
  "ai@dmp.com": "Demo AI Engineer",
};

interface CurrentUserResponse {
  id: string;
  email: string;
  full_name: string;
  role: string;
  contact_number?: string | null;
  assigned_site_ids?: string[];
  is_global_admin?: boolean;
}

function decodeBase64Url(value: string) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
  return window.atob(padded);
}

export function decodeTokenPayload(token: string): JwtPayload | null {
  try {
    const [, payload] = token.split(".");
    if (!payload) return null;
    return JSON.parse(decodeBase64Url(payload)) as JwtPayload;
  } catch {
    return null;
  }
}

export function roleLabel(role?: string) {
  if (!role) return "User";
  return role.replace(/_/g, " ");
}

function normalizeRole(role?: string): AuthRole {
  if (!role) return "User";
  const normalized = role.toLowerCase();

  if (normalized === "admin") return "Admin";
  if (normalized === "operator") return "Operator";
  if (normalized === "ai_engineer" || normalized === "ai engineer" || normalized === "ai") return "AI_Engineer";

  if (role === "Admin" || role === "Operator" || role === "AI_Engineer") {
    return role;
  }
  return "User";
}

function defaultFullName(email: string) {
  const [local] = email.split("@");
  return local
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function buildSession(token: LoginResponse): AuthSession {
  const payload = decodeTokenPayload(token.access_token);
  const email = payload?.sub ?? "";
  const role = normalizeRole(payload?.role);
  const expiresAt = payload?.exp ? payload.exp * 1000 : Date.now();

  if (!email || expiresAt <= Date.now()) {
    throw new Error("The authentication response was invalid.");
  }

  return {
    accessToken: token.access_token,
    tokenType: token.token_type,
    expiresAt,
    user: {
      email,
      fullName: USER_NAMES[email] ?? defaultFullName(email),
      role,
      roleLabel: roleLabel(role),
      contactNumber: null,
      assignedSiteIds: [],
      isGlobalAdmin: false,
    },
  };
}

function applyCurrentUser(session: AuthSession, user: CurrentUserResponse): AuthSession {
  const role = normalizeRole(user.role);
  return {
    ...session,
    user: {
      id: user.id,
      email: user.email,
      fullName: user.full_name,
      role,
      roleLabel: roleLabel(role),
      contactNumber: user.contact_number ?? null,
      assignedSiteIds: user.assigned_site_ids ?? [],
      isGlobalAdmin: Boolean(user.is_global_admin),
    },
  };
}

async function fetchCurrentUser(accessToken: string): Promise<CurrentUserResponse> {
  const response = await fetch(`${API_BASE}/api/v1/auth/me`, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
  });

  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as { detail?: string; error?: string } | null;
    throw new Error(data?.detail ?? data?.error ?? "Unable to load the current user.");
  }

  return response.json() as Promise<CurrentUserResponse>;
}

export async function refreshSessionUser(session: AuthSession): Promise<AuthSession> {
  const currentUser = await fetchCurrentUser(session.accessToken);
  return applyCurrentUser(session, currentUser);
}

export async function login(credentials: LoginCredentials): Promise<AuthSession> {
  const body = new URLSearchParams();
  body.set("username", credentials.email.trim());
  body.set("password", credentials.password);

  const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body,
  });

  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(data?.detail ?? "Unable to sign in with those credentials.");
  }

  const session = buildSession((await response.json()) as LoginResponse);
  return refreshSessionUser(session);
}

export function readStoredSession(): AuthSession | null {
  if (typeof window === "undefined") return null;

  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw) as AuthSession;
    if (!session.accessToken || session.expiresAt <= Date.now()) {
      clearStoredSession();
      return null;
    }
    session.user.role = normalizeRole(session.user.role);
    session.user.roleLabel = session.user.roleLabel ?? roleLabel(session.user.role);
    session.user.contactNumber = session.user.contactNumber ?? null;
    session.user.assignedSiteIds = session.user.assignedSiteIds ?? [];
    session.user.isGlobalAdmin = Boolean(session.user.isGlobalAdmin);
    return session;
  } catch {
    clearStoredSession();
    return null;
  }
}

export function getStoredAccessToken() {
  return readStoredSession()?.accessToken ?? null;
}

export function authHeaders() {
  const token = getStoredAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : undefined;
}

export function storeSession(session: AuthSession) {
  if (typeof window === "undefined") return;

  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function clearStoredSession() {
  if (typeof window === "undefined") return;

  window.localStorage.removeItem(SESSION_STORAGE_KEY);
}
