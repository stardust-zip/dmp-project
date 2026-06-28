# Frontend Testing Plan

**Project**: DMP Platform — Next.js 16 + React 19 + TypeScript
**Status**: Zero test tooling installed
**Target directory**: `frontend/`

---

## Overview

| Phase | Scope | Tool | Priority |
|---|---|---|---|
| 1 | Pure lib functions | Vitest | High — security-critical logic |
| 2 | Auth component rendering | Vitest + React Testing Library | High — access-control UI |
| 3 | Critical E2E flows | Playwright | Medium — regression guard |

Phases 1 and 2 share the same Vitest setup. Phase 3 is a separate install and can be adopted independently.

---

## Shared Vitest Setup (Phases 1 and 2)

### Packages to install

```
vitest@^3.0
@vitejs/plugin-react@^4.0
@vitest/coverage-v8@^3.0
jsdom@^26.0
@testing-library/react@^16.0
@testing-library/user-event@^14.0
@testing-library/jest-dom@^6.0
```

Install as `devDependencies`. Vitest 3.x supports React 19 and Vite 6 without additional shims.

### `frontend/vitest.config.ts`

Key config decisions:

1. **Plugin**: `@vitejs/plugin-react` — handles JSX transform.
2. **Environment**: `jsdom` — required for `window.localStorage`, `window.atob`, and RTL rendering.
3. **Path alias**: mirror `tsconfig.json` — declare `@/*` → `./src/*` under `resolve.alias` (Vitest uses Vite's resolver, not TypeScript's `paths`).
4. **Setup file**: `src/test/setup.ts` that imports `@testing-library/jest-dom` matchers.
5. **Coverage**: provider `v8`, include `src/lib/**` and `src/components/**`, exclude `*-api.ts` fetch wrappers in Phase 1.
6. **Globals**: `true` — avoids per-file `import { describe, it, expect }`.

```ts
// frontend/vitest.config.ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": resolve(__dirname, "./src") },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    coverage: {
      provider: "v8",
      include: ["src/lib/**", "src/components/**"],
      exclude: ["src/lib/*-api.ts", "src/**/*.d.ts"],
      thresholds: { lines: 80, functions: 80 },
    },
  },
});
```

### `frontend/src/test/setup.ts`

```ts
import "@testing-library/jest-dom";
```

### `package.json` script additions

```json
"test": "vitest run",
"test:watch": "vitest",
"coverage": "vitest run --coverage"
```

`vitest run` = single-pass CI mode. `vitest` (no subcommand) = watch mode for local dev.

---

## Phase 1 — Unit Tests for Pure Lib Functions

**Rationale**: `rbac.ts` gates every protected route — a regression here is a security incident. `format.ts` has non-trivial string parsing with a token override map and prefix-stripping logic where edge cases are easy to miss. Both are pure functions with no I/O, so tests are fast and deterministic with zero mocking.

### Files to create

```
frontend/src/test/setup.ts
frontend/src/lib/__tests__/rbac.test.ts
frontend/src/lib/__tests__/format.test.ts
frontend/src/lib/__tests__/auth-api.test.ts
```

### `rbac.test.ts` — describe/it outline

```
describe("hasAnyRole")
  it("returns true when no roles constraint is given")
  it("returns true when roles array is empty")
  it("returns false when user is null")
  it("returns false when user is undefined")
  it("returns true when user role is in the allowed list")
  it("returns false when user role is not in the allowed list")
  it("is case-sensitive — 'admin' does not match 'Admin'")

describe("canAccessPath")
  it("grants access to null user on unrestricted path /anomaly")
  it("denies Operator on /models")
  it("grants Admin on /models")
  it("grants AI_Engineer on /models")
  it("denies AI_Engineer on /users")
  it("grants Admin on /users")
  it("grants Operator, AI_Engineer, Admin on /assets")
  it("handles sub-paths — /models/detail/123 still enforces AI_ENGINEERING_ROLES")
  it("handles sub-paths — /users/edit/abc still enforces USER_MANAGEMENT_ROLES")
  it("returns true for unknown paths")

describe("role constant arrays")
  it("USER_MANAGEMENT_ROLES contains only Admin")
  it("ASSET_DASHBOARD_ROLES contains Admin, AI_Engineer, Operator")
```

### `format.test.ts` — describe/it outline

```
describe("humanizeIdentifier")
  it("returns 'Unspecified' for undefined, null, empty, and whitespace-only")
  it("applies HUMAN_TOKEN_OVERRIDES — 'ai' → 'AI', 'hvac' → 'HVAC', 'kwh' → 'kWh'")
  it("splits on underscore, hyphen, and space")
  it("title-cases unknown tokens")
  it("collapses multiple delimiters — 'foo__bar' → 'Foo Bar'")

describe("displayModelName")
  it("returns 'Unnamed Model' for nullish input")
  it("formats dmp_energy_prediction prefix — extracts location and metric")
  it("falls back to humanizeIdentifier when only one part remains after stripping")
  it("strips leading dmp_ from non-energy-prediction names")

describe("displayDeviceName")
  it("returns 'Unnamed Device' for nullish input")
  it("strips 'meter' prefix and formats as 'X Meter - Location'")
  it("falls back to humanizeIdentifier when only one part remains after stripping")

describe("displayLocationName")
  it("returns 'Unnamed Location' for nullish name and id")
  it("strips 'building' and 'site' prefixes")
  it("falls back to id when name is empty")

describe("timeAgo")
  // Use vi.setSystemTime() to control Date.now()
  it("returns seconds notation for < 60s")
  it("returns minutes notation for < 1h")
  it("returns hours notation for < 24h")
  it("returns days notation for >= 24h")

describe("fmt / fmt1 / fmtKwh")
  it("fmt rounds to nearest integer and formats with commas")
  it("fmt1 always shows one decimal place")
  it("fmtKwh shows 3 decimal places when |n| < 1")
  it("fmtKwh rounds to integer when |n| >= 1")
  it("fmtKwh handles negative values — |-0.5| < 1 triggers decimal format")
```

### `auth-api.test.ts` — describe/it outline

Covers only exports that don't call `fetch`: `decodeTokenPayload`, `roleLabel`, `buildSession`, `readStoredSession`, `storeSession`, `clearStoredSession`. Mock `fetch`-dependent functions (`login`, `refreshSessionUser`) in consumer tests.

```
describe("decodeTokenPayload")
  it("returns null for a malformed token with no dots")
  it("returns null when payload segment is not valid JSON")
  it("decodes a valid base64url JWT payload without padding")
  it("decodes a valid base64url JWT payload that needs padding")
  it("returns null when payload segment is missing")

describe("roleLabel")
  it("returns 'User' for undefined")
  it("replaces underscores with spaces — 'AI_Engineer' → 'AI Engineer'")
  it("returns plain strings unchanged")

describe("buildSession")
  it("throws when token payload has no sub (empty email)")
  it("throws when expiresAt is in the past")
  it("constructs a valid AuthSession from a well-formed LoginResponse")
  it("maps AI_Engineer role correctly via normalizeRole")
  it("maps Admin role correctly")

describe("readStoredSession")
  it("returns null when localStorage is empty")
  it("returns null when stored session is expired")
  it("returns null when stored JSON is corrupt")
  it("re-normalizes role on read — handles legacy casing")
  it("returns a valid session when storage contains unexpired data")
  // Use beforeEach/afterEach with localStorage via jsdom
```

### Acceptance criteria — Phase 1

- `npm run test` exits 0
- `npm run coverage` reports >= 80% line and function coverage for `rbac.ts`, `format.ts`, and non-fetch exports of `auth-api.ts`
- `npm run typecheck` still passes
- Tests complete in < 5 seconds

---

## Phase 2 — React Testing Library Component Tests

**Rationale**: `AuthGate` controls every access-control rendering decision. It has three distinct states (loading spinner, access-denied card, children render) and redirect side-effects via `useRouter`. RTL exercises the real React tree without a browser.

**Scope**: `auth-gate.tsx`, `auth-provider.tsx`. Feature-page components are excluded — they are thin wrappers over API calls; cover them in Phase 3.

### Environment notes

- `next/navigation`: mock via `vi.mock("next/navigation", ...)` returning stub implementations of `usePathname` and `useRouter`.
- `window.setTimeout`: `auth-gate.tsx` uses `window.setTimeout(() => setMounted(true), 0)` on mount. Call `vi.useFakeTimers()` in `beforeEach` and `await act(() => vi.runAllTimersAsync())` after `render()` to flush the mount tick before asserting.
- `window.localStorage`: provided by jsdom — no mock needed.
- `window.atob`: provided by jsdom — no mock needed.

### Files to create

```
frontend/src/components/auth/__tests__/auth-gate.test.tsx
frontend/src/components/auth/__tests__/auth-provider.test.tsx
frontend/src/test/factories/auth.ts   (shared test data builders)
```

#### `src/test/factories/auth.ts`

Export `makeUser(overrides?)` and `makeSession(overrides?)` returning typed `AuthUser` / `AuthSession` with safe defaults and an `expiresAt` well in the future. Keeps test bodies concise, avoids fixture copy-paste.

### `auth-gate.test.tsx` — describe/it outline

```
beforeEach
  vi.mock("next/navigation") — stub usePathname and useRouter
  vi.useFakeTimers()

afterEach
  vi.useRealTimers()

describe("unauthenticated user")
  it("renders spinner before mount timeout resolves")
  it("redirects to /login?next=/dashboard after mount on protected route")
  it("renders children on /login (public route) without redirecting")

describe("authenticated, authorized")
  it("renders children on /dashboard for any role")
  it("renders children on /models for Admin")
  it("renders children on /models for AI_Engineer")
  it("renders children on /assets for Operator")

describe("authenticated, unauthorized")
  it("renders access-denied card on /models for Operator")
  it("renders access-denied card on /users for AI_Engineer")
  it("does NOT redirect — stays on page and shows denial card")
  it("access-denied card contains heading 'Access restricted'")

describe("authenticated on public route")
  it("redirects to /dashboard when authenticated user navigates to /login")

describe("status: loading")
  it("renders spinner while status is 'loading', does not redirect")
```

### `auth-provider.test.tsx` — describe/it outline

```
// vi.mock("@/lib/auth-api") — mock login and refreshSessionUser

describe("initial state")
  it("exposes status 'unauthenticated' with null session when localStorage is empty")
  it("reads and exposes an unexpired session from localStorage on mount")
  it("treats an expired session in localStorage as unauthenticated")

describe("signIn")
  it("calls login() with credentials and updates session state")
  it("exposes isAuthenticated: true after successful signIn")
  it("propagates error thrown by login()")

describe("signOut")
  it("clears session state and sets isAuthenticated to false")
  it("removes item from localStorage under key 'dmp.auth.session'")

describe("session expiry timer")
  it("auto-clears session when expiresAt is reached")
  // vi.useFakeTimers() + vi.advanceTimersByTime()

describe("useAuth outside provider")
  it("throws 'useAuth must be used within AuthProvider'")
```

### Acceptance criteria — Phase 2

- All RTL tests pass with `npm run test`
- No real `fetch` calls — `login` and `refreshSessionUser` are mocked via `vi.mock("@/lib/auth-api")`
- No real `next/navigation` calls — router and pathname fully stubbed
- Coverage for `auth-gate.tsx` and `auth-provider.tsx` >= 80% lines
- Tests are deterministic (no real timer calls)
- `npm run typecheck` still passes

---

## Phase 3 — Playwright E2E Tests

**Rationale**: Phases 1–2 test units in isolation. E2E tests catch integration failures — broken API routing, missing environment variables, Next.js middleware regressions, and auth redirect loops — that unit tests cannot detect.

**Scope**: Login flow, role-based redirect, access-denied path. Keep the suite small (< 10 tests) and stable. Feature-specific E2E tests are deferred until the app reaches production stability.

### Packages to install

```
@playwright/test@^1.50
```

Install as `devDependency`. Run `npx playwright install --with-deps chromium` once to install the browser binary (also run this as a CI step).

### `frontend/playwright.config.ts` — key settings

- `baseURL`: read from `process.env.PLAYWRIGHT_BASE_URL`, default `http://localhost:3000`
- `testDir`: `./src/e2e`
- `use.browserName`: `chromium` for CI; add `firefox` when suite is stable
- `webServer`: conditionally start `npm run dev` when `process.env.CI` is unset
- `retries`: 1 in CI, 0 locally
- `reporter`: `html` locally, `github` in CI

### `package.json` additions for Phase 3

```json
"e2e": "playwright test",
"e2e:ui": "playwright test --ui"
```

### Files to create

```
frontend/playwright.config.ts
frontend/src/e2e/auth.spec.ts
frontend/src/e2e/rbac-redirect.spec.ts
```

### `auth.spec.ts` — describe/it outline

```
test.describe("Login flow")
  test("shows login form on /login")
  test("redirects unauthenticated user from /dashboard to /login?next=/dashboard")
  test("Admin can log in and reaches /dashboard")
  test("shows error message on invalid credentials")

test.describe("Logout")
  test("after signOut, navigating to /dashboard redirects to /login")
```

### `rbac-redirect.spec.ts` — describe/it outline

```
// Use Playwright storageState to inject a pre-built localStorage session
// (key: "dmp.auth.session") — avoids real login API calls per test.
// Set expiresAt to Date.now() + 3_600_000.

test.describe("Operator role")
  test("can access /dashboard and /anomaly")
  test("is shown access-denied on /models")
  test("is shown access-denied on /users")

test.describe("AI_Engineer role")
  test("can access /models and /monitoring")
  test("is shown access-denied on /users")

test.describe("Admin role")
  test("can access all protected routes without access-denied")
```

### Acceptance criteria — Phase 3

- `npm run e2e` passes against a running `npm run dev` server with real backend
- Auth tests do not rely on real network credentials — `storageState` fixture injects sessions
- No `page.waitForTimeout()` — use `page.waitForURL()`, `expect(locator).toBeVisible()`, `page.waitForSelector()`
- CI E2E job completes in < 3 minutes
- Flaky policy: any test that fails non-deterministically twice in CI is quarantined and tracked as a GitHub issue before re-enabling

---

## CI Integration

The existing `.github/workflows/ci.yml` pipeline has three gates: lint → tests (parallel) → build. Frontend tests slot into Gate 2 alongside backend pytest jobs.

### New job: `frontend-unit-tests`

Add to `ci.yml` under Gate 2:

```yaml
frontend-unit-tests:
  name: "Frontend Unit & Component Tests"
  runs-on: ubuntu-latest
  needs: lint
  defaults:
    run:
      working-directory: frontend
  steps:
    - uses: actions/checkout@v6
    - uses: actions/setup-node@v4
      with:
        node-version: "22"
        cache: "npm"
        cache-dependency-path: frontend/package-lock.json
    - run: npm ci
    - run: npm run typecheck
    - run: npm run coverage
    - uses: actions/upload-artifact@v4
      if: always()
      with:
        name: coverage-report
        path: frontend/coverage/
```

Also add `frontend-unit-tests` to the `needs` list of the existing `docker-compose-build` job:

```yaml
docker-compose-build:
  needs: [unit-tests, integration-tests, infrastructure-tests, frontend-unit-tests]
```

### New job: `frontend-e2e` (Phase 3)

```yaml
frontend-e2e:
  name: "Frontend E2E"
  runs-on: ubuntu-latest
  needs: [frontend-unit-tests, unit-tests, integration-tests, infrastructure-tests]
  # Requires a running backend — start docker-compose services before this job,
  # or use Playwright's route() API to intercept fetch calls at the browser level.
```

Run E2E after all unit-level gates because it is slower and requires a server.

---

## Implementation Sequence

| Step | Action | Effort |
|---|---|---|
| 1 | Install Vitest + RTL devDeps, create `vitest.config.ts` and `src/test/setup.ts` | 30 min |
| 2 | Add `test` / `coverage` scripts, verify `npm run test` runs with no tests (exit 0) | 5 min |
| 3 | Write `rbac.test.ts` — 100% coverage is achievable, logic is ~25 lines | 1 h |
| 4 | Write `format.test.ts` — focus on edge cases in `humanizeIdentifier`, `displayModelName`, `displayDeviceName` | 2 h |
| 5 | Write `auth-api.test.ts` — jsdom provides `window.atob`; mock `fetch` only for `login`/`refreshSessionUser` in consumer tests | 1.5 h |
| 6 | Write `auth-gate.test.tsx` + `auth-provider.test.tsx` — mock `next/navigation` and `@/lib/auth-api` | 2 h |
| 7 | Add `frontend-unit-tests` job to `ci.yml` | 20 min |
| 8 | Install Playwright, write `auth.spec.ts` and `rbac-redirect.spec.ts` | 3 h |
| 9 | Add `frontend-e2e` CI job | 30 min |

**Total estimated effort: ~10.5 hours**

---

## Key Pitfalls

**`resolve.alias` required in `vitest.config.ts`**: Vitest uses Vite's resolver, not TypeScript's `moduleResolution`. The `@/*` alias must be declared under `resolve.alias` independently of `tsconfig.paths`. Omitting this causes `Cannot find module '@/lib/rbac'` at test runtime even though TypeScript compiles cleanly.

**`"use client"` directive**: Vitest does not strip Next.js directives. They are silently ignored — no action needed.

**`window.setTimeout` in `AuthGate`**: The mount effect uses `window.setTimeout(() => setMounted(true), 0)`. In RTL tests, call `vi.useFakeTimers()` before render, then `await act(() => vi.runAllTimersAsync())` to flush the mount tick before asserting redirect calls.

**`next/navigation` in RTL**: `usePathname`, `useRouter`, and `useSearchParams` are not available outside Next.js runtime. Mock the entire module inline or via a `__mocks__/next/` directory:

```ts
vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
  useRouter: vi.fn(),
  useSearchParams: vi.fn(),
}));
```

**Playwright `storageState`**: To inject a pre-built session without a real login, serialize an `AuthSession` object as a `localStorage` entry under key `"dmp.auth.session"`. Set `expiresAt` to `Date.now() + 3_600_000`. Pass as `storageState` in the Playwright fixture.
