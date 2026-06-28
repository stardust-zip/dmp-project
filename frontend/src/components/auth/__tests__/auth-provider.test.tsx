import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthProvider, useAuth } from "@/components/auth/auth-provider";
import * as authApi from "@/lib/auth-api";
import { makeSession } from "@/test/factories/auth";

vi.mock("@/lib/auth-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/auth-api")>();

  return {
    ...actual,
    login: vi.fn(),
    refreshSessionUser: vi.fn(async (session) => session),
  };
});

function AuthProbe() {
  const { session, status, token, isAuthenticated, signIn, signOut } = useAuth();

  return (
    <div>
      <div>Status: {status}</div>
      <div>Token: {token ?? "none"}</div>
      <div>Authenticated: {String(isAuthenticated)}</div>
      <div>User: {session?.user.email ?? "none"}</div>
      <button type="button" onClick={() => void signIn({ email: "admin@dmp.com", password: "secret" })}>
        Sign in
      </button>
      <button type="button" onClick={signOut}>
        Sign out
      </button>
    </div>
  );
}

function renderProvider() {
  return render(
    <AuthProvider>
      <AuthProbe />
    </AuthProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(authApi.login).mockReset();
  vi.mocked(authApi.refreshSessionUser).mockReset();
  vi.mocked(authApi.refreshSessionUser).mockImplementation(async (session) => session);
});

afterEach(() => {
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("initial state", () => {
  it("exposes unauthenticated status with null session when localStorage is empty", () => {
    renderProvider();

    expect(screen.getByText("Status: unauthenticated")).toBeInTheDocument();
    expect(screen.getByText("User: none")).toBeInTheDocument();
  });

  it("reads and exposes an unexpired session from localStorage on mount", () => {
    authApi.storeSession(makeSession({ accessToken: "stored-token" }));

    renderProvider();

    expect(screen.getByText("Status: authenticated")).toBeInTheDocument();
    expect(screen.getByText("Token: stored-token")).toBeInTheDocument();
    expect(screen.getByText("User: admin@dmp.com")).toBeInTheDocument();
  });

  it("treats an expired session in localStorage as unauthenticated", () => {
    window.localStorage.setItem("dmp.auth.session", JSON.stringify(makeSession({ expiresAt: Date.now() - 1 })));

    renderProvider();

    expect(screen.getByText("Status: unauthenticated")).toBeInTheDocument();
  });
});

describe("signIn", () => {
  it("calls login with credentials and updates session state", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.login).mockResolvedValue(makeSession({ accessToken: "signed-in-token" }));
    renderProvider();

    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(screen.getByText("Token: signed-in-token")).toBeInTheDocument());
    expect(authApi.login).toHaveBeenCalledWith({ email: "admin@dmp.com", password: "secret" });
  });

  it("exposes isAuthenticated true after successful signIn", async () => {
    const user = userEvent.setup();
    vi.mocked(authApi.login).mockResolvedValue(makeSession());
    renderProvider();

    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(screen.getByText("Authenticated: true")).toBeInTheDocument());
  });

  it("propagates error thrown by login", async () => {
    const error = new Error("Bad credentials");
    vi.mocked(authApi.login).mockRejectedValue(error);

    function SignInCaller() {
      const { signIn } = useAuth();
      return (
        <button type="button" onClick={() => void signIn({ email: "bad@dmp.com", password: "wrong" }).catch((caught) => window.dispatchEvent(new CustomEvent("signin-error", { detail: caught })))}>
          Try sign in
        </button>
      );
    }

    render(
      <AuthProvider>
        <SignInCaller />
      </AuthProvider>,
    );

    const observed = new Promise((resolve) => {
      window.addEventListener("signin-error", (event) => resolve((event as CustomEvent).detail), { once: true });
    });
    await userEvent.click(screen.getByRole("button", { name: "Try sign in" }));

    await expect(observed).resolves.toBe(error);
  });
});

describe("signOut", () => {
  it("clears session state and sets isAuthenticated to false", async () => {
    const user = userEvent.setup();
    authApi.storeSession(makeSession());
    renderProvider();

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(screen.getByText("Status: unauthenticated")).toBeInTheDocument();
    expect(screen.getByText("Authenticated: false")).toBeInTheDocument();
  });

  it("removes item from localStorage under the auth session key", async () => {
    const user = userEvent.setup();
    authApi.storeSession(makeSession());
    renderProvider();

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(window.localStorage.getItem("dmp.auth.session")).toBeNull();
  });
});

describe("session expiry timer", () => {
  it("auto-clears session when expiresAt is reached", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-28T12:00:00Z"));
    authApi.storeSession(makeSession({ expiresAt: Date.now() + 1_000 }));
    renderProvider();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });

    expect(screen.getByText("Status: unauthenticated")).toBeInTheDocument();
  });
});

describe("useAuth outside provider", () => {
  it("throws a helpful error", () => {
    function OutsideProvider() {
      useAuth();
      return null;
    }

    expect(() => render(<OutsideProvider />)).toThrow("useAuth must be used within AuthProvider");
  });
});
