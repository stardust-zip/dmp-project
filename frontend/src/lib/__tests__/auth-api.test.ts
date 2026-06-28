import {
  authHeaders,
  buildSession,
  clearStoredSession,
  decodeTokenPayload,
  getStoredAccessToken,
  login,
  readStoredSession,
  refreshSessionUser,
  roleLabel,
  storeSession,
} from "@/lib/auth-api";
import { makeSession } from "@/test/factories/auth";
import type { JwtPayload } from "@/types/auth";

const STORAGE_KEY = "dmp.auth.session";

function encodePayload(payload: JwtPayload) {
  return window
    .btoa(JSON.stringify(payload))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function tokenFor(payload: JwtPayload) {
  return `header.${encodePayload(payload)}.signature`;
}

describe("decodeTokenPayload", () => {
  it("returns null for a malformed token with no dots", () => {
    expect(decodeTokenPayload("not-a-token")).toBeNull();
  });

  it("returns null when payload segment is not valid JSON", () => {
    expect(decodeTokenPayload("header.bm90LWpzb24.signature")).toBeNull();
  });

  it("decodes a valid base64url JWT payload without padding", () => {
    expect(decodeTokenPayload(tokenFor({ sub: "admin@dmp.com", role: "Admin", exp: 1_850_000_000 }))).toEqual({
      sub: "admin@dmp.com",
      role: "Admin",
      exp: 1_850_000_000,
    });
  });

  it("decodes a valid base64url JWT payload that needs padding", () => {
    expect(decodeTokenPayload("header.eyJzdWIiOiJhQGIuYyJ9.signature")).toEqual({ sub: "a@b.c" });
  });

  it("returns null when payload segment is missing", () => {
    expect(decodeTokenPayload("header..signature")).toBeNull();
  });
});

describe("roleLabel", () => {
  it("returns User for undefined", () => {
    expect(roleLabel()).toBe("User");
  });

  it("replaces underscores with spaces", () => {
    expect(roleLabel("AI_Engineer")).toBe("AI Engineer");
  });

  it("returns plain strings unchanged", () => {
    expect(roleLabel("Operator")).toBe("Operator");
  });
});

describe("buildSession", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-28T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("throws when token payload has no sub", () => {
    expect(() => buildSession({ access_token: tokenFor({ role: "Admin", exp: 1_850_000_000 }), token_type: "bearer" })).toThrow(
      "The authentication response was invalid.",
    );
  });

  it("throws when expiresAt is in the past", () => {
    expect(() => buildSession({ access_token: tokenFor({ sub: "admin@dmp.com", role: "Admin", exp: 1 }), token_type: "bearer" })).toThrow(
      "The authentication response was invalid.",
    );
  });

  it("constructs a valid AuthSession from a well-formed LoginResponse", () => {
    const session = buildSession({
      access_token: tokenFor({ sub: "operator@dmp.com", role: "Operator", exp: 1_850_000_000 }),
      token_type: "bearer",
    });

    expect(session).toMatchObject({
      accessToken: expect.any(String),
      tokenType: "bearer",
      expiresAt: 1_850_000_000_000,
      user: {
        email: "operator@dmp.com",
        fullName: "Demo Operator",
        role: "Operator",
        roleLabel: "Operator",
      },
    });
  });

  it("maps AI_Engineer role correctly via normalizeRole", () => {
    const session = buildSession({
      access_token: tokenFor({ sub: "ai@dmp.com", role: "ai" as JwtPayload["role"], exp: 1_850_000_000 }),
      token_type: "bearer",
    });

    expect(session.user.role).toBe("AI_Engineer");
  });

  it("maps Admin role correctly", () => {
    const session = buildSession({
      access_token: tokenFor({ sub: "admin@dmp.com", role: "admin" as JwtPayload["role"], exp: 1_850_000_000 }),
      token_type: "bearer",
    });

    expect(session.user.role).toBe("Admin");
  });
});

describe("stored session helpers", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-28T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it("readStoredSession returns null when localStorage is empty", () => {
    expect(readStoredSession()).toBeNull();
  });

  it("readStoredSession returns null when stored session is expired", () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(makeSession({ expiresAt: Date.now() - 1 })));

    expect(readStoredSession()).toBeNull();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("readStoredSession returns null when stored JSON is corrupt", () => {
    window.localStorage.setItem(STORAGE_KEY, "{bad json");

    expect(readStoredSession()).toBeNull();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("readStoredSession re-normalizes role and fills legacy defaults", () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        ...makeSession(),
        user: {
          email: "ai@dmp.com",
          fullName: "Demo AI Engineer",
          role: "ai",
        },
      }),
    );

    expect(readStoredSession()?.user).toMatchObject({
      role: "AI_Engineer",
      roleLabel: "AI Engineer",
      contactNumber: null,
      assignedSiteIds: [],
      isGlobalAdmin: false,
    });
  });

  it("readStoredSession returns a valid session when storage contains unexpired data", () => {
    const session = makeSession();
    storeSession(session);

    expect(readStoredSession()).toEqual(session);
  });

  it("storeSession persists and clearStoredSession removes the session", () => {
    storeSession(makeSession());
    expect(window.localStorage.getItem(STORAGE_KEY)).toEqual(expect.any(String));

    clearStoredSession();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("getStoredAccessToken and authHeaders reflect the stored session", () => {
    storeSession(makeSession({ accessToken: "stored-token" }));

    expect(getStoredAccessToken()).toBe("stored-token");
    expect(authHeaders()).toEqual({ Authorization: "Bearer stored-token" });

    clearStoredSession();
    expect(getStoredAccessToken()).toBeNull();
    expect(authHeaders()).toBeUndefined();
  });
});

describe("fetch-backed auth helpers", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-28T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("refreshSessionUser applies current user data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          id: "user-1",
          email: "ai@dmp.com",
          full_name: "AI Engineer",
          role: "ai_engineer",
          contact_number: "555-0100",
          assigned_site_ids: ["site-1"],
          is_global_admin: false,
        }),
      })),
    );

    await expect(refreshSessionUser(makeSession())).resolves.toMatchObject({
      user: {
        id: "user-1",
        email: "ai@dmp.com",
        fullName: "AI Engineer",
        role: "AI_Engineer",
        assignedSiteIds: ["site-1"],
      },
    });
  });

  it("refreshSessionUser throws API error details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        json: async () => ({ detail: "Not authorized" }),
      })),
    );

    await expect(refreshSessionUser(makeSession())).rejects.toThrow("Not authorized");
  });

  it("login posts credentials and returns the refreshed session", async () => {
    const accessToken = tokenFor({ sub: "admin@dmp.com", role: "admin" as JwtPayload["role"], exp: 1_850_000_000 });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ access_token: accessToken, token_type: "bearer" }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            id: "admin-1",
            email: "admin@dmp.com",
            full_name: "Admin User",
            role: "Admin",
          }),
        }),
    );

    await expect(login({ email: " admin@dmp.com ", password: "secret" })).resolves.toMatchObject({
      accessToken,
      user: { id: "admin-1", role: "Admin" },
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/backend/api/v1/auth/login",
      expect.objectContaining({
        method: "POST",
        body: expect.any(URLSearchParams),
      }),
    );
  });

  it("login throws detail from failed login response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        json: async () => ({ detail: "Invalid credentials" }),
      })),
    );

    await expect(login({ email: "bad@dmp.com", password: "wrong" })).rejects.toThrow("Invalid credentials");
  });
});
