import { act, render, screen } from "@testing-library/react";
import { usePathname, useRouter } from "next/navigation";
import { AuthGate } from "@/components/auth/auth-gate";
import { useAuth } from "@/components/auth/auth-provider";
import { makeSession, makeUser } from "@/test/factories/auth";
import type { AuthSession } from "@/types/auth";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
  useRouter: vi.fn(),
  useSearchParams: vi.fn(),
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: vi.fn(),
}));

const replace = vi.fn();

function setGateState({
  pathname = "/dashboard",
  session = null,
  status = session ? "authenticated" : "unauthenticated",
}: {
  pathname?: string;
  session?: AuthSession | null;
  status?: "loading" | "authenticated" | "unauthenticated";
}) {
  vi.mocked(usePathname).mockReturnValue(pathname);
  vi.mocked(useRouter).mockReturnValue({ replace } as never);
  vi.mocked(useAuth).mockReturnValue({
    session,
    status,
    token: session?.accessToken ?? null,
    isAuthenticated: Boolean(session),
    signIn: vi.fn(),
    signOut: vi.fn(),
  });
}

async function flushMount() {
  await act(async () => {
    await vi.runAllTimersAsync();
  });
}

function renderGate() {
  return render(
    <AuthGate>
      <div>Protected content</div>
    </AuthGate>,
  );
}

beforeEach(() => {
  replace.mockReset();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("unauthenticated user", () => {
  it("renders spinner before mount timeout resolves", () => {
    setGateState({});
    const { container } = renderGate();

    expect(container.querySelector(".auth-loading svg")).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });

  it("redirects to /login?next=/dashboard after mount on protected route", async () => {
    setGateState({ pathname: "/dashboard" });
    renderGate();

    await flushMount();

    expect(replace).toHaveBeenCalledWith("/login?next=%2Fdashboard");
  });

  it("renders children on /login without redirecting", async () => {
    setGateState({ pathname: "/login" });
    renderGate();

    await flushMount();

    expect(screen.getByText("Protected content")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("authenticated, authorized", () => {
  it("renders children on /dashboard for any role", async () => {
    setGateState({ pathname: "/dashboard", session: makeSession({ user: makeUser({ role: "User" }) }) });
    renderGate();

    await flushMount();

    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });

  it("renders children on /models for Admin", async () => {
    setGateState({ pathname: "/models", session: makeSession({ user: makeUser({ role: "Admin" }) }) });
    renderGate();

    await flushMount();

    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });

  it("renders children on /models for AI_Engineer", async () => {
    setGateState({ pathname: "/models", session: makeSession({ user: makeUser({ role: "AI_Engineer" }) }) });
    renderGate();

    await flushMount();

    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });

  it("renders children on /assets for Operator", async () => {
    setGateState({ pathname: "/assets", session: makeSession({ user: makeUser({ role: "Operator" }) }) });
    renderGate();

    await flushMount();

    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });
});

describe("authenticated, unauthorized", () => {
  it("renders access-denied card on /models for Operator", async () => {
    setGateState({ pathname: "/models", session: makeSession({ user: makeUser({ role: "Operator" }) }) });
    renderGate();

    await flushMount();

    expect(screen.getByRole("heading", { name: "Access restricted" })).toBeInTheDocument();
  });

  it("renders access-denied card on /users for AI_Engineer", async () => {
    setGateState({ pathname: "/users", session: makeSession({ user: makeUser({ role: "AI_Engineer" }) }) });
    renderGate();

    await flushMount();

    expect(screen.getByRole("heading", { name: "Access restricted" })).toBeInTheDocument();
  });

  it("does not redirect and stays on page with denial card", async () => {
    setGateState({ pathname: "/users", session: makeSession({ user: makeUser({ role: "Operator" }) }) });
    renderGate();

    await flushMount();

    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Access restricted" })).toBeInTheDocument();
  });
});

describe("authenticated on public route", () => {
  it("redirects to /dashboard when authenticated user navigates to /login", async () => {
    setGateState({ pathname: "/login", session: makeSession() });
    renderGate();

    await flushMount();

    expect(replace).toHaveBeenCalledWith("/dashboard");
  });
});

describe("status: loading", () => {
  it("renders spinner while loading and does not redirect", async () => {
    setGateState({ status: "loading" });
    const { container } = renderGate();

    await flushMount();

    expect(container.querySelector(".auth-loading svg")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
