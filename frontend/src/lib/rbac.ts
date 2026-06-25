import type { AuthRole, AuthUser } from "@/types/auth";
import type { IconName } from "@/types";

export const AI_ENGINEERING_ROLES: AuthRole[] = ["Admin", "AI_Engineer"];
export const ASSET_DASHBOARD_ROLES: AuthRole[] = ["Admin", "AI_Engineer", "Operator"];
export const ASSET_MANAGEMENT_ROLES: AuthRole[] = ["Admin"];
export const USER_MANAGEMENT_ROLES: AuthRole[] = ["Admin"];

export interface NavItem {
  href: string;
  label: string;
  icon: IconName;
  badge?: number;
  roles?: AuthRole[];
}

export const MAIN_NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: "grid", roles: ASSET_DASHBOARD_ROLES },
  { href: "/anomaly", label: "Anomaly Detection", icon: "pulse" },
  { href: "/forecast", label: "Forecasting", icon: "trend" },
  { href: "/assets", label: "Assets", icon: "map", roles: ASSET_MANAGEMENT_ROLES },
  { href: "/models", label: "AI Engineering", icon: "cpu", roles: AI_ENGINEERING_ROLES },
  { href: "/users", label: "Users", icon: "users", roles: USER_MANAGEMENT_ROLES },
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
    return hasAnyRole(user, ASSET_DASHBOARD_ROLES);
  }
  if (pathname.startsWith("/users")) {
    return hasAnyRole(user, USER_MANAGEMENT_ROLES);
  }
  return true;
}
