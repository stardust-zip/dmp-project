import { expect, test, type Page } from "@playwright/test";

function encodeJwtPayload(payload: Record<string, unknown>) {
  return Buffer.from(JSON.stringify(payload)).toString("base64url");
}

function tokenFor(role = "Admin") {
  return `header.${encodeJwtPayload({ sub: "admin@dmp.com", role, exp: Math.floor(Date.now() / 1000) + 3600 })}.signature`;
}

async function mockSuccessfulLogin(page: Page) {
  await page.route("**/api/backend/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ access_token: tokenFor(), token_type: "bearer" }),
    });
  });
  await page.route("**/api/backend/api/v1/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "admin-1",
        email: "admin@dmp.com",
        full_name: "Demo Admin",
        role: "Admin",
        assigned_site_ids: [],
        is_global_admin: true,
      }),
    });
  });
}

async function seedSession(page: Page) {
  await page.goto("/login");
  await page.evaluate((session) => {
    window.localStorage.setItem("dmp.auth.session", JSON.stringify(session));
  }, {
    accessToken: tokenFor(),
    tokenType: "bearer",
    expiresAt: Date.now() + 3_600_000,
    user: {
      id: "admin-1",
      email: "admin@dmp.com",
      fullName: "Demo Admin",
      role: "Admin",
      roleLabel: "Admin",
      contactNumber: null,
      assignedSiteIds: [],
      isGlobalAdmin: true,
    },
  });
}

test.describe("Login flow", () => {
  test("shows login form on /login", async ({ page }) => {
    await page.goto("/login");

    await expect(page.getByRole("heading", { name: "Data Platform" })).toBeVisible();
    await expect(page.getByLabel("Email")).toBeVisible();
    await expect(page.getByLabel("Password")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });

  test("redirects unauthenticated user from /dashboard to login with next path", async ({ page }) => {
    await page.goto("/dashboard");
    await page.waitForURL(/\/login/);

    expect(new URL(page.url()).searchParams.get("next")).toBe("/dashboard");
  });

  test("Admin can log in and reaches /dashboard", async ({ page }) => {
    await mockSuccessfulLogin(page);
    await page.goto("/login");

    await page.getByLabel("Email").fill("admin@dmp.com");
    await page.getByLabel("Password").fill("demo123");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page).toHaveURL(/\/dashboard$/);
  });

  test("shows error message on invalid credentials", async ({ page }) => {
    await page.route("**/api/backend/api/v1/auth/login", async (route) => {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Invalid credentials" }),
      });
    });
    await page.goto("/login");

    await page.getByLabel("Email").fill("admin@dmp.com");
    await page.getByLabel("Password").fill("wrong");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByText("Invalid credentials")).toBeVisible();
  });
});

test.describe("Logout", () => {
  test("after signOut, navigating to /dashboard redirects to /login", async ({ page }) => {
    await seedSession(page);
    await page.goto("/dashboard");
    await page.locator(".profile").click();
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect.poll(() => page.evaluate(() => window.localStorage.getItem("dmp.auth.session"))).toBeNull();

    await page.goto("/dashboard");
    await page.waitForURL(/\/login/);

    expect(new URL(page.url()).searchParams.get("next")).toBe("/dashboard");
  });
});
