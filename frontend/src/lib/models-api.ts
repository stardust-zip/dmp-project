import { authHeaders } from "@/lib/auth-api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/backend";

export interface RegisteredModel {
  name: string;
  description?: string | null;
  creation_timestamp?: number | null;
  last_updated_timestamp?: number | null;
  tags: Record<string, string>;
  latest_versions: Array<{
    version: string;
    current_stage?: string | null;
    status?: string | null;
  }>;
}

export interface ModelVersion {
  name: string;
  version: string;
  run_id: string;
  model_task?: ModelTask | null;
  metrics: Record<string, number>;
  tags: Record<string, string>;
  current_stage?: string | null;
  creation_timestamp?: number | null;
  last_updated_timestamp?: number | null;
}

export interface LocationOption {
  id: string;
  parent_id?: string | null;
  name: string;
  location_type?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface MetricOption {
  id: string;
  unit?: string | null;
  description?: string | null;
}

export interface PipelineLog {
  id: string;
  type: string;
  model_task?: string | null;
  status: string;
  mlflow_run_id?: string | null;
  datasource_used?: string | null;
  execution_time_ms?: number | null;
  timestamp?: string | null;
}

export type ModelTask = "forecasting" | "anomaly_detection" | "prediction";
export type TrainingDataSource = "csv" | "db";

export interface TrainModelPayload {
  site_id: string;
  building_id?: string | null;
  metrics: string[];
  time_range_start: string;
  time_range_end: string;
  model_task: ModelTask;
  data_source: TrainingDataSource;
  csv_path?: string | null;
}

export interface TrainModelResponse {
  message: string;
  task_id: string;
  model_task: ModelTask;
  data_source: TrainingDataSource;
  algorithm: string;
  site_id: string;
  building_id?: string | null;
  metrics: string[];
  triggered_by: string;
}

export interface RollbackModelPayload {
  mlflow_run_id: string;
  model_name?: string | null;
}

export interface RollbackModelResponse {
  message: string;
  model_name: string;
  version: string;
  run_id: string;
  promoted_by: string;
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
    const data = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(data?.detail ?? `API request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function getRegisteredModels(signal?: AbortSignal) {
  return apiGet<{ models: RegisteredModel[] }>("/api/v1/models/", signal);
}

export function getModelVersions(modelName: string, signal?: AbortSignal) {
  return apiGet<{ model_name: string; versions: ModelVersion[] }>(`/api/v1/models/${encodeURIComponent(modelName)}/versions`, signal);
}

export function getPipelineLogs(signal?: AbortSignal) {
  return apiGet<{ limit: number; offset: number; logs: PipelineLog[] }>("/api/v1/models/logs/pipeline", signal);
}

export function trainModel(payload: TrainModelPayload, signal?: AbortSignal) {
  return apiPost<TrainModelResponse>("/api/v1/models/train", payload, signal);
}

export function rollbackModel(payload: RollbackModelPayload, signal?: AbortSignal) {
  return apiPost<RollbackModelResponse>("/api/v1/models/rollback", payload, signal);
}

export interface LocationQuery {
  q?: string;
  locationType?: string;
  parentId?: string;
  limit?: number;
}

export function getLocationOptions(query?: LocationQuery, signal?: AbortSignal) {
  const search = new URLSearchParams();
  if (query?.q) search.set("q", query.q);
  if (query?.locationType) search.set("location_type", query.locationType);
  if (query?.parentId) search.set("parent_id", query.parentId);
  if (query?.limit) search.set("limit", String(query.limit));
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet<{ locations: LocationOption[] }>(`/api/v1/metadata/locations${suffix}`, signal);
}

export function getMetricOptions(signal?: AbortSignal) {
  return apiGet<{ metrics: MetricOption[] }>("/api/v1/metadata/metrics", signal);
}
