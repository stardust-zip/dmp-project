export type AuthRole = "Admin" | "Operator" | "AI_Engineer" | "User";

export interface AuthUser {
  id?: string;
  email: string;
  fullName: string;
  role: AuthRole;
  roleLabel: string;
  contactNumber?: string | null;
  assignedSiteIds: string[];
  isGlobalAdmin: boolean;
}

export interface AuthSession {
  accessToken: string;
  tokenType: string;
  expiresAt: number;
  user: AuthUser;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface JwtPayload {
  sub?: string;
  role?: AuthRole;
  exp?: number;
}
