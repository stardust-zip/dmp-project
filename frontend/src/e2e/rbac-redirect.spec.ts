import { expect, test, type Page } from "@playwright/test";
import type { AuthRole } from "@/types/auth";

function makeSession(role: AuthRole) {
  const emailByRole: Record<AuthRole, string> = {
    Admin: "admin@dmp.com",
    AI_Engineer: "ai@dmp.com",
    Operator: "operator@dmp.com",
    User: "user@dmp.com",
  };
  const email = emailByRole[role];

  return {
    accessToken: "e2e-token",
    tokenType: "bearer",
    expiresAt: Date.now() + 3_600_000,
    user: {
      id: `${role.toLowerCase()}-1`,
      email,
      fullName: role.replace(/_/g, " "),
      role,
      roleLabel: role.replace(/_/g, " "),
      contactNumber: null,
      assignedSiteIds: [],
      isGlobalAdmin: role === "Admin",
    },
  };
}

async function loginAs(page: Page, role: AuthRole) {
  await page.addInitScript((session) => {
    window.localStorage.setItem("dmp.auth.session", JSON.stringify(session));
  }, makeSession(role));
}

async function expectAllowed(page: Page, path: string) {
  await page.goto(path);
  await expect(page).toHaveURL(new RegExp(`${path}$`));
  await expect(page.getByRole("heading", { name: "Access restricted" })).toHaveCount(0);
}

async function expectDenied(page: Page, path: string) {
  await page.goto(path);
  await expect(page.getByRole("heading", { name: "Access restricted" })).toBeVisible();
}

test.describe("Operator role", () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, "Operator");
  });

  test("can access /dashboard and /anomaly", async ({ page }) => {
    await expectAllowed(page, "/dashboard");
    await expectAllowed(page, "/anomaly");
  });

  test("is shown access-denied on /models", async ({ page }) => {
    await expectDenied(page, "/models");
  });

  test("is shown access-denied on /users", async ({ page }) => {
    await expectDenied(page, "/users");
  });
});

test.describe("AI_Engineer role", () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, "AI_Engineer");
  });

  test("can access /models and /monitoring", async ({ page }) => {
    await expectAllowed(page, "/models");
    await expectAllowed(page, "/monitoring");
  });

  test("is shown access-denied on /users", async ({ page }) => {
    await expectDenied(page, "/users");
  });
});

test.describe("Admin role", () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page, "Admin");
  });

  test("can access all protected routes without access-denied", async ({ page }) => {
    for (const path of ["/dashboard", "/anomaly", "/assets", "/models", "/monitoring", "/experiments", "/users"]) {
      await expectAllowed(page, path);
    }
  });
});
