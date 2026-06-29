"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { clearStoredSession, login as loginRequest, readStoredSession, refreshSessionUser, storeSession } from "@/lib/auth-api";
import { DEFAULT_SIM_BOUNDS, setIsPlaying, setSimNow } from "@/lib/simulation-store";
import type { AuthSession, LoginCredentials } from "@/types/auth";

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  session: AuthSession | null;
  status: AuthStatus;
  token: string | null;
  isAuthenticated: boolean;
  signIn: (credentials: LoginCredentials) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(() => readStoredSession());
  const status: AuthStatus = session ? "authenticated" : "unauthenticated";
  const accessToken = session?.accessToken ?? null;

  useEffect(() => {
    if (!session) return undefined;

    const timeoutMs = Math.max(session.expiresAt - Date.now(), 0);
    const timeout = window.setTimeout(() => {
      clearStoredSession();
      setSession(null);
    }, timeoutMs);

    return () => window.clearTimeout(timeout);
  }, [session]);

  useEffect(() => {
    if (!accessToken) return undefined;

    const timeout = window.setTimeout(async () => {
      try {
        const storedSession = readStoredSession();
        if (!storedSession || storedSession.accessToken !== accessToken) return;

        const refreshed = await refreshSessionUser(storedSession);
        storeSession(refreshed);
        setSession(refreshed);
      } catch {
        // Keep the existing token session if the profile refresh is temporarily unavailable.
      }
    }, 0);

    return () => window.clearTimeout(timeout);
  }, [accessToken]);

  const signIn = useCallback(async (credentials: LoginCredentials) => {
    const nextSession = await loginRequest(credentials);
    storeSession(nextSession);
    setSession(nextSession);
    setSimNow(DEFAULT_SIM_BOUNDS.start);
    setIsPlaying(false);
  }, []);

  const signOut = useCallback(() => {
    clearStoredSession();
    setSession(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      status,
      token: session?.accessToken ?? null,
      isAuthenticated: status === "authenticated",
      signIn,
      signOut,
    }),
    [session, signIn, signOut, status],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
