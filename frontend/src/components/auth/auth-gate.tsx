"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Icon } from "@/components/common/icons";
import { canAccessPath } from "@/lib/rbac";

const PUBLIC_ROUTES = new Set(["/login"]);

export function AuthGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { session, status, isAuthenticated } = useAuth();
  const isPublicRoute = PUBLIC_ROUTES.has(pathname);
  const canAccess = isPublicRoute || !isAuthenticated || canAccessPath(session?.user, pathname);

  useEffect(() => {
    if (status === "loading") return;

    if (!isAuthenticated && !isPublicRoute) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }

    if (isAuthenticated && isPublicRoute) {
      router.replace("/dashboard");
    }
  }, [isAuthenticated, isPublicRoute, pathname, router, status]);

  if (status === "loading" || (!isAuthenticated && !isPublicRoute) || (isAuthenticated && isPublicRoute)) {
    return (
      <div className="auth-loading">
        <Icon name="refresh" />
      </div>
    );
  }

  if (!canAccess) {
    return (
      <main className="access-denied">
        <div className="card">
          <div className="card-body">
            <span className="card-icon">
              <Icon name="shield" />
            </span>
            <h1>Access restricted</h1>
            <p>Your current role does not include access to this workspace.</p>
          </div>
        </div>
      </main>
    );
  }

  return children;
}
