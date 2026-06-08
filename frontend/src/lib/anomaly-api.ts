import type {
  AnomalyEventsResponse,
  AnomalyFacets,
  AnomalyOverview,
  AnomalyTimelineResponse,
} from "@/types";
import { authHeaders } from "@/lib/auth-api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/backend";

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

async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    signal,
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getAnomalyOverview(query: AnomalyQuery, signal?: AbortSignal) {
  return apiGet<AnomalyOverview>(`/api/v1/anomalies/overview${params(query)}`, signal);
}

export function getAnomalyEvents(query: AnomalyQuery, signal?: AbortSignal) {
  return apiGet<AnomalyEventsResponse>(`/api/v1/anomalies/events${params(query)}`, signal);
}

export function getAnomalyTimeline(query: AnomalyQuery, signal?: AbortSignal) {
  return apiGet<AnomalyTimelineResponse>(`/api/v1/anomalies/timeline${params(query)}`, signal);
}

export function getAnomalyFacets(site?: string, signal?: AbortSignal) {
  const qs = site && site !== "all" ? `?site_id=${encodeURIComponent(site)}` : "";
  return apiGet<AnomalyFacets>(`/api/v1/anomalies/facets${qs}`, signal);
}
