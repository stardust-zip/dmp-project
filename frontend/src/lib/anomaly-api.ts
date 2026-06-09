import type {
  AnomalyEventsResponse,
  AnomalyFacets,
  AnomalyOverview,
  AnomalyTimelineResponse,
} from "@/types";
import { authHeaders } from "@/lib/auth-api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/backend";
const API_PREFIX = "/api/v1";

export type AnomalyQuery = {
  site?: string;
  building?: string;
  severity?: string;
  type?: string;
  start?: string;
  end?: string;
  limit?: number;
  offset?: number;
  sort?: "severity" | "newest" | "oldest" | "duration";
};

function params(query: AnomalyQuery = {}) {
  const search = new URLSearchParams();
  if (query.site && query.site !== "all") search.set("site_id", query.site);
  if (query.building && query.building !== "all") search.set("building_id", query.building);
  if (query.severity && query.severity !== "all") search.set("severity", query.severity);
  if (query.type && query.type !== "all") search.set("type", query.type);
  if (query.start) search.set("start", query.start);
  if (query.end) search.set("end", query.end);
  if (query.limit != null) search.set("limit", String(query.limit));
  if (query.offset != null) search.set("offset", String(query.offset));
  if (query.sort) search.set("sort", query.sort);
  const value = search.toString();
  return value ? `?${value}` : "";
}

async function responseError(response: Response) {
  const data = (await response.json().catch(() => null)) as {
    detail?: string | string[];
    error?: {
      message?: string;
      details?: Record<string, unknown>;
    };
  } | null;
  const detail = Array.isArray(data?.detail) ? data.detail.join(" ") : data?.detail;
  const message = data?.error?.message ?? detail ?? `API request failed: ${response.status}`;
  const path = typeof data?.error?.details?.path === "string" ? data.error.details.path : null;
  return path ? `${message} Missing file: ${path}` : message;
}

async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const base = API_BASE.replace(/\/$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const versionedPath = base.endsWith(API_PREFIX) ? normalizedPath : `${API_PREFIX}${normalizedPath}`;
  const response = await fetch(`${base}${versionedPath}`, {
    signal,
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  return response.json() as Promise<T>;
}

export function getAnomalyOverview(query: AnomalyQuery, signal?: AbortSignal) {
  return apiGet<AnomalyOverview>(`/anomalies/overview${params(query)}`, signal);
}

export function getAnomalyEvents(query: AnomalyQuery, signal?: AbortSignal) {
  return apiGet<AnomalyEventsResponse>(`/anomalies/events${params(query)}`, signal);
}

export function getAnomalyTimeline(query: AnomalyQuery, signal?: AbortSignal) {
  return apiGet<AnomalyTimelineResponse>(`/anomalies/timeline${params(query)}`, signal);
}

export function getAnomalyFacets(site?: string, signal?: AbortSignal) {
  const qs = site && site !== "all" ? `?site_id=${encodeURIComponent(site)}` : "";
  return apiGet<AnomalyFacets>(`/anomalies/facets${qs}`, signal);
}
