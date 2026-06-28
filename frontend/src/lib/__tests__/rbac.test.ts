import {
  AI_ENGINEERING_ROLES,
  ASSET_DASHBOARD_ROLES,
  USER_MANAGEMENT_ROLES,
  canAccessPath,
  hasAnyRole,
} from "@/lib/rbac";
import { makeUser } from "@/test/factories/auth";
import type { AuthRole } from "@/types/auth";

describe("hasAnyRole", () => {
  it("returns true when no roles constraint is given", () => {
    expect(hasAnyRole(null)).toBe(true);
  });

  it("returns true when roles array is empty", () => {
    expect(hasAnyRole(undefined, [])).toBe(true);
  });

  it("returns false when user is null", () => {
    expect(hasAnyRole(null, ["Admin"])).toBe(false);
  });

  it("returns false when user is undefined", () => {
    expect(hasAnyRole(undefined, ["Admin"])).toBe(false);
  });

  it("returns true when user role is in the allowed list", () => {
    expect(hasAnyRole(makeUser({ role: "AI_Engineer" }), AI_ENGINEERING_ROLES)).toBe(true);
  });

  it("returns false when user role is not in the allowed list", () => {
    expect(hasAnyRole(makeUser({ role: "Operator" }), AI_ENGINEERING_ROLES)).toBe(false);
  });

  it("is case-sensitive", () => {
    expect(hasAnyRole(makeUser({ role: "Admin" }), ["admin" as AuthRole])).toBe(false);
  });
});

describe("canAccessPath", () => {
  it("grants access to null user on unrestricted path /anomaly", () => {
    expect(canAccessPath(null, "/anomaly")).toBe(true);
  });

  it("denies Operator on /models", () => {
    expect(canAccessPath(makeUser({ role: "Operator" }), "/models")).toBe(false);
  });

  it("grants Admin on /models", () => {
    expect(canAccessPath(makeUser({ role: "Admin" }), "/models")).toBe(true);
  });

  it("grants AI_Engineer on /models", () => {
    expect(canAccessPath(makeUser({ role: "AI_Engineer" }), "/models")).toBe(true);
  });

  it("denies AI_Engineer on /users", () => {
    expect(canAccessPath(makeUser({ role: "AI_Engineer" }), "/users")).toBe(false);
  });

  it("grants Admin on /users", () => {
    expect(canAccessPath(makeUser({ role: "Admin" }), "/users")).toBe(true);
  });

  it("grants Operator, AI_Engineer, and Admin on /assets", () => {
    expect(canAccessPath(makeUser({ role: "Operator" }), "/assets")).toBe(true);
    expect(canAccessPath(makeUser({ role: "AI_Engineer" }), "/assets")).toBe(true);
    expect(canAccessPath(makeUser({ role: "Admin" }), "/assets")).toBe(true);
  });

  it("handles /models sub-paths", () => {
    expect(canAccessPath(makeUser({ role: "Operator" }), "/models/detail/123")).toBe(false);
  });

  it("handles /users sub-paths", () => {
    expect(canAccessPath(makeUser({ role: "Operator" }), "/users/edit/abc")).toBe(false);
  });

  it("enforces monitoring roles", () => {
    expect(canAccessPath(makeUser({ role: "AI_Engineer" }), "/monitoring")).toBe(true);
    expect(canAccessPath(makeUser({ role: "Operator" }), "/monitoring")).toBe(false);
  });

  it("enforces experiment roles", () => {
    expect(canAccessPath(makeUser({ role: "Admin" }), "/experiments")).toBe(true);
    expect(canAccessPath(makeUser({ role: "User" }), "/experiments")).toBe(false);
  });

  it("returns true for unknown paths", () => {
    expect(canAccessPath(undefined, "/does-not-exist")).toBe(true);
  });
});

describe("role constant arrays", () => {
  it("USER_MANAGEMENT_ROLES contains only Admin", () => {
    expect(USER_MANAGEMENT_ROLES).toEqual(["Admin"]);
  });

  it("ASSET_DASHBOARD_ROLES contains Admin, AI_Engineer, and Operator", () => {
    expect(ASSET_DASHBOARD_ROLES).toEqual(["Admin", "AI_Engineer", "Operator"]);
  });
});
