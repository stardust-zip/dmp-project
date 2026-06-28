import type { AuthRole, AuthSession, AuthUser } from "@/types/auth";

export function makeUser(overrides: Partial<AuthUser> = {}): AuthUser {
  const role: AuthRole = overrides.role ?? "Admin";

  return {
    email: "admin@dmp.com",
    fullName: "Demo Admin",
    role,
    roleLabel: role.replace(/_/g, " "),
    contactNumber: null,
    assignedSiteIds: [],
    isGlobalAdmin: role === "Admin",
    ...overrides,
  };
}

export function makeSession(overrides: Partial<AuthSession> = {}): AuthSession {
  return {
    accessToken: "test-access-token",
    tokenType: "bearer",
    expiresAt: Date.now() + 60 * 60 * 1000,
    user: makeUser(),
    ...overrides,
  };
}
