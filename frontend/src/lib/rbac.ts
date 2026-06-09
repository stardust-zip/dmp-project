import type { AuthRole, AuthUser } from "@/types/auth";
import type { IconName } from "@/types";

export const AI_ENGINEERING_ROLES: AuthRole[] = ["Admin", "AI_Engineer"];
export const ASSET_MANAGEMENT_ROLES: AuthRole[] = ["Admin"];

export interface NavItem {
  href: string;
  label: string;
  icon: IconName;
  badge?: number;
  roles?: AuthRole[];
}

export const MAIN_NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: "grid" },
  { href: "/anomaly", label: "Anomaly Detection", icon: "pulse", badge: 15 },
  { href: "/forecast", label: "Forecasting", icon: "trend" },
  { href: "/models", label: "AI Engineering", icon: "cpu", roles: AI_ENGINEERING_ROLES },
  { href: "/assets", label: "Sites & Meters", icon: "map", roles: ASSET_MANAGEMENT_ROLES },
];

export function hasAnyRole(user: AuthUser | null | undefined, roles?: AuthRole[]) {
  if (!roles?.length) return true;
  if (!user) return false;
  return roles.includes(user.role);
}

export function canAccessPath(user: AuthUser | null | undefined, pathname: string) {
  if (pathname.startsWith("/models")) {
    return hasAnyRole(user, AI_ENGINEERING_ROLES);
  }
  if (pathname.startsWith("/assets")) {
    return hasAnyRole(user, ASSET_MANAGEMENT_ROLES);
  }
  return true;
}
