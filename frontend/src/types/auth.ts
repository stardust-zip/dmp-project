export type AuthRole = "Admin" | "Operator" | "AI_Engineer" | "PO" | "Developer" | "User";

export interface AuthUser {
  email: string;
  fullName: string;
  role: AuthRole;
  roleLabel: string;
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
