"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { clearStoredSession, login as loginRequest, readStoredSession, storeSession } from "@/lib/auth-api";
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
  const [session, setSession] = useState<AuthSession | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  useEffect(() => {
    const storedSession = readStoredSession();
    setSession(storedSession);
    setStatus(storedSession ? "authenticated" : "unauthenticated");
  }, []);

  useEffect(() => {
    if (!session) return undefined;

    const timeoutMs = Math.max(session.expiresAt - Date.now(), 0);
    const timeout = window.setTimeout(() => {
      clearStoredSession();
      setSession(null);
      setStatus("unauthenticated");
    }, timeoutMs);

    return () => window.clearTimeout(timeout);
  }, [session]);

  const signIn = useCallback(async (credentials: LoginCredentials) => {
    const nextSession = await loginRequest(credentials);
    storeSession(nextSession);
    setSession(nextSession);
    setStatus("authenticated");
  }, []);

  const signOut = useCallback(() => {
    clearStoredSession();
    setSession(null);
    setStatus("unauthenticated");
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
