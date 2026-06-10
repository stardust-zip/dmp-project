import { authHeaders } from "@/lib/auth-api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/backend";

export interface PredictionHourlyPoint {
  timestamp: string;
  expected_value: number;
}

export interface PredictionScenarioPayload {
  site_id: string;
  building_id: string;
  metric_type: string;
  scenario_date: string;
  opening_time: string;
  closing_time: string;
  unit_rate?: number | null;
  model_name?: string | null;
}

export interface PredictionScenarioResponse {
  site_id: string;
  building_id: string;
  metric_type: string;
  model_name: string;
  model_version: string;
  estimated_value: number;
  estimated_cost?: number | null;
  unit: string;
  points: PredictionHourlyPoint[];
}

export interface ExpectedActualPayload {
  site_id: string;
  building_id: string;
  metric_type: string;
  start_time: string;
  end_time: string;
  opening_time: string;
  closing_time: string;
  model_name?: string | null;
}

export interface ExpectedActualPoint {
  timestamp: string;
  expected_value: number;
  actual_value?: number | null;
  variance?: number | null;
  variance_percent?: number | null;
}

export interface ExpectedActualResponse {
  site_id: string;
  building_id: string;
  metric_type: string;
  model_name: string;
  model_version: string;
  expected_total: number;
  actual_total?: number | null;
  variance_total?: number | null;
  variance_percent?: number | null;
  unit: string;
  points: ExpectedActualPoint[];
}

async function apiPost<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    signal,
    headers: {
      ...authHeaders(),
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as {
      detail?: string | string[];
      error?: string;
    } | null;
    const detail = Array.isArray(data?.detail) ? data.detail.join(" ") : data?.detail;
    throw new Error(detail ?? data?.error ?? `API request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function predictScenario(payload: PredictionScenarioPayload, signal?: AbortSignal) {
  return apiPost<PredictionScenarioResponse>("/api/v1/prediction/scenario", payload, signal);
}

export function getExpectedVsActual(payload: ExpectedActualPayload, signal?: AbortSignal) {
  return apiPost<ExpectedActualResponse>("/api/v1/prediction/expected-vs-actual", payload, signal);
}
