import { authHeaders } from "@/lib/auth-api";
import { API_BASE } from "@/lib/api-base";

export interface RegisteredModel {
  name: string;
  description?: string | null;
  creation_timestamp?: number | null;
  last_updated_timestamp?: number | null;
  tags: Record<string, string>;
  production_version?: {
    version: string;
    run_id?: string | null;
    current_stage?: string | null;
    status?: string | null;
  } | null;
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
  archived?: boolean;
}

export interface MetricOption {
  id: string;
  unit?: string | null;
  description?: string | null;
}

export interface DeviceOption {
  id: string;
  building_id: string;
  device_type_id: string;
  status: string;
  metric_type_ids: string[];
}

export interface CreateSitePayload {
  id: string;
  name: string;
  metadata?: Record<string, unknown> | null;
}

export interface CreateBuildingPayload {
  id: string;
  site_id: string;
  name: string;
  location_type_id?: string;
  metadata?: Record<string, unknown> | null;
}

export interface UpdateLocationPayload {
  name?: string;
  parent_id?: string;
  location_type_id?: string;
  metadata?: Record<string, unknown> | null;
  archived?: boolean;
}

export interface CreateMetricPayload {
  id: string;
  unit?: string | null;
  description?: string | null;
}

export interface UpdateMetricPayload {
  unit?: string | null;
  description?: string | null;
}

export interface RegisterDevicePayload {
  id: string;
  building_id: string;
  device_type_id?: string;
  status?: string;
  metric_type_ids?: string[];
}

export interface UpdateDevicePayload {
  building_id?: string;
  device_type_id?: string;
  status?: string;
  metric_type_ids?: string[];
}

export interface DeviceQuery {
  buildingId?: string;
  metricTypeId?: string;
  status?: string;
  limit?: number;
}

export interface PipelineLog {
  id: string;
  type: string;
  model_task?: string | null;
  status: string;
  mlflow_run_id?: string | null;
  celery_task_id?: string | null;
  datasource_used?: string | null;
  execution_time_ms?: number | null;
  timestamp?: string | null;
  terminal_log?: string | null;
}

export type ModelTask = "forecasting" | "anomaly_detection" | "prediction";
export type TrainingDataSource = "csv" | "db";

export interface TrainModelPayload {
  site_id: string | null;
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

export interface TrainingValidationMetric {
  metric: string;
  known_metric: boolean;
  db_rows: number;
  csv_rows: number;
  available_in_db: boolean;
  available_in_csv: boolean;
  enough_rows: boolean;
  required_rows: number;
  messages: string[];
}

export interface TrainingValidationResponse {
  valid: boolean;
  data_source: TrainingDataSource;
  site_id: string;
  building_id?: string | null;
  target_building_ids: string[];
  required_rows_per_metric: number;
  errors: string[];
  warnings: string[];
  metrics: TrainingValidationMetric[];
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

export interface UpdateModelDescriptionPayload {
  description: string;
}

export interface UpdateModelDescriptionResponse {
  name: string;
  description: string;
  updated_by: string;
}

type ApiErrorPayload = {
  detail?: unknown;
  error?: unknown;
  message?: unknown;
};

function formatApiDetail(detail: unknown): string | null {
  if (!detail) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const loc = "loc" in item && Array.isArray(item.loc) ? item.loc.join(".") : null;
          return loc ? `${loc}: ${String(item.msg)}` : String(item.msg);
        }
        return null;
      })
      .filter(Boolean)
      .join(" ");
  }
  return null;
}

async function apiErrorMessage(response: Response): Promise<string> {
  if (response.status === 502) {
    return "Backend is unavailable. Confirm the dmp_backend container is running and healthy, then refresh this page.";
  }

  const data = (await response.json().catch(() => null)) as ApiErrorPayload | null;
  const detail = formatApiDetail(data?.detail);
  const error = typeof data?.error === "string" ? data.error : null;
  const message = typeof data?.message === "string" ? data.message : null;
  return detail ?? error ?? message ?? `API request failed: ${response.status}`;
}

async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    signal,
    headers: authHeaders(),
  });

  if (!response.ok) {
    throw new Error(await apiErrorMessage(response));
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
    throw new Error(await apiErrorMessage(response));
  }

  return response.json() as Promise<T>;
}

async function apiPatch<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    signal,
    headers: {
      ...authHeaders(),
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(await apiErrorMessage(response));
  }

  return response.json() as Promise<T>;
}

export function getRegisteredModels(signal?: AbortSignal) {
  return apiGet<{ models: RegisteredModel[] }>("/api/v1/models/", signal);
}

export function getModelVersions(modelName: string, signal?: AbortSignal) {
  return apiGet<{ model_name: string; versions: ModelVersion[] }>(`/api/v1/models/${encodeURIComponent(modelName)}/versions`, signal);
}

export function updateModelDescription(modelName: string, payload: UpdateModelDescriptionPayload, signal?: AbortSignal) {
  return apiPatch<UpdateModelDescriptionResponse>(`/api/v1/models/${encodeURIComponent(modelName)}/description`, payload, signal);
}

export function getPipelineLogs(signal?: AbortSignal) {
  return apiGet<{ limit: number; offset: number; logs: PipelineLog[] }>("/api/v1/models/logs/pipeline", signal);
}

export function cancelPipelineLog(logId: string, signal?: AbortSignal) {
  return apiPost<{ id: string; status: string; cancelled_by: string }>(
    `/api/v1/models/logs/${encodeURIComponent(logId)}/cancel`,
    {},
    signal,
  );
}

export function trainModel(payload: TrainModelPayload, signal?: AbortSignal) {
  return apiPost<TrainModelResponse>("/api/v1/models/train", payload, signal);
}

export function validateTrainingRequest(payload: TrainModelPayload, signal?: AbortSignal) {
  return apiPost<TrainingValidationResponse>("/api/v1/models/train/validate", payload, signal);
}

export function rollbackModel(payload: RollbackModelPayload, signal?: AbortSignal) {
  return apiPost<RollbackModelResponse>("/api/v1/models/rollback", payload, signal);
}

export function demoteModel(payload: RollbackModelPayload, signal?: AbortSignal) {
  return apiPost<RollbackModelResponse>("/api/v1/models/demote", payload, signal);
}

export interface LocationQuery {
  q?: string;
  locationType?: string;
  parentId?: string;
  includeArchived?: boolean;
  limit?: number;
}

export function getLocationOptions(query?: LocationQuery, signal?: AbortSignal) {
  const search = new URLSearchParams();
  if (query?.q) search.set("q", query.q);
  if (query?.locationType) search.set("location_type", query.locationType);
  if (query?.parentId) search.set("parent_id", query.parentId);
  if (query?.includeArchived) search.set("include_archived", "true");
  if (query?.limit) search.set("limit", String(query.limit));
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet<{ locations: LocationOption[] }>(`/api/v1/metadata/locations${suffix}`, signal);
}

export function getMetricOptions(signal?: AbortSignal) {
  return apiGet<{ metrics: MetricOption[] }>("/api/v1/metadata/metrics", signal);
}

export function createSite(payload: CreateSitePayload, signal?: AbortSignal) {
  return apiPost<LocationOption>("/api/v1/metadata/sites", payload, signal);
}

export function createBuilding(payload: CreateBuildingPayload, signal?: AbortSignal) {
  return apiPost<LocationOption>("/api/v1/metadata/buildings", payload, signal);
}

export function updateLocation(locationId: string, payload: UpdateLocationPayload, signal?: AbortSignal) {
  return apiPatch<LocationOption>(`/api/v1/metadata/locations/${encodeURIComponent(locationId)}`, payload, signal);
}

export function createMetric(payload: CreateMetricPayload, signal?: AbortSignal) {
  return apiPost<MetricOption>("/api/v1/metadata/metrics", payload, signal);
}

export function updateMetric(metricId: string, payload: UpdateMetricPayload, signal?: AbortSignal) {
  return apiPatch<MetricOption>(`/api/v1/metadata/metrics/${encodeURIComponent(metricId)}`, payload, signal);
}

export function registerDevice(payload: RegisterDevicePayload, signal?: AbortSignal) {
  return apiPost<DeviceOption>("/api/v1/metadata/devices", payload, signal);
}

export function getDevices(query?: DeviceQuery, signal?: AbortSignal) {
  const search = new URLSearchParams();
  if (query?.buildingId) search.set("building_id", query.buildingId);
  if (query?.metricTypeId) search.set("metric_type_id", query.metricTypeId);
  if (query?.status) search.set("status", query.status);
  if (query?.limit) search.set("limit", String(query.limit));
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet<{ devices: DeviceOption[] }>(`/api/v1/metadata/devices${suffix}`, signal);
}

export function updateDevice(deviceId: string, payload: UpdateDevicePayload, signal?: AbortSignal) {
  return apiPatch<DeviceOption>(`/api/v1/metadata/devices/${encodeURIComponent(deviceId)}`, payload, signal);
}

export function deactivateDevice(deviceId: string, signal?: AbortSignal) {
  return apiPost<DeviceOption>(`/api/v1/metadata/devices/${encodeURIComponent(deviceId)}/deactivate`, {}, signal);
}

export interface AnomalyBackfillPayload {
  time_range_start: string;
  time_range_end: string;
}

export interface AnomalyBackfillResponse {
  message: string;
  task_id: string;
  pipeline_log_id: string;
  time_range_start: string;
  time_range_end: string;
  triggered_by: string;
}

export function backfillAnomalyInference(payload: AnomalyBackfillPayload, signal?: AbortSignal) {
  return apiPost<AnomalyBackfillResponse>("/api/v1/models/anomaly/backfill", payload, signal);
}

export async function downloadModelFile(
  modelName: string,
  version: string,
  signal?: AbortSignal,
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(
    `${API_BASE}/api/v1/models/${encodeURIComponent(modelName)}/versions/${encodeURIComponent(version)}/download`,
    { signal, headers: authHeaders() },
  );

  if (!response.ok) {
    throw new Error(await apiErrorMessage(response));
  }

  const disposition = response.headers.get("content-disposition") ?? "";
  const filenameMatch = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
  const filename = filenameMatch
    ? filenameMatch[1].replace(/['"]/g, "")
    : `${modelName}_v${version}.zip`;

  return { blob: await response.blob(), filename };
}
