import { authHeaders } from "@/lib/auth-api";
import { API_BASE } from "@/lib/api-base";

export interface MonitoringAlert {
  id: string;
  model_name: string;
  model_version: string;
  drift_type: string;
  feature_name: string | null;
  severity: string;
  drift_score: number;
  is_drifted: boolean;
  message: string;
  computed_at: string;
}

export interface MonitoringAlertsResponse {
  model_name: string;
  model_version: string | null;
  alerts: MonitoringAlert[];
  total: number;
}

export interface PerformanceMetric {
  id: string;
  model_name: string;
  model_version: string;
  mlflow_run_id: string;
  model_task: string;
  building_id: string | null;
  metric_type_id: string | null;
  period_start: string;
  period_end: string;
  sample_count: number;
  mae: number | null;
  rmse: number | null;
  mape: number | null;
  r2_score: number | null;
  mean_error: number | null;
  p10_error: number | null;
  p90_error: number | null;
  baseline_mae: number | null;
  baseline_rmse: number | null;
  performance_ratio: number | null;
  computed_at: string;
}

export interface PerformanceTimelineResponse {
  model_name: string;
  model_version: string;
  metrics: PerformanceMetric[];
}

export interface DriftReport {
  id: string;
  model_name: string;
  model_version: string;
  mlflow_run_id: string;
  model_task: string;
  drift_type: string;
  feature_name: string | null;
  period_start: string;
  period_end: string;
  drift_score: number;
  drift_threshold: number;
  is_drifted: boolean;
  severity: string;
  reference_stats: Record<string, unknown>;
  current_stats: Record<string, unknown>;
  details: Record<string, unknown> | null;
  computed_at: string;
}

export interface DriftTimelineResponse {
  model_name: string;
  model_version: string;
  overall_drift: DriftReport[];
  feature_drift: Record<string, DriftReport[]>;
}

export interface MonitoringSummary {
  model_name: string;
  model_version: string;
  health_score: number;
  status: "healthy" | "degraded" | "critical";
  last_performance: PerformanceMetric | null;
  active_drifts: DriftReport[];
  total_predictions: number;
  pending_actuals: number;
}

export interface VersionComparisonEntry {
  version: string;
  mae: number | null;
  rmse: number | null;
  mape: number | null;
  r2_score: number | null;
  mean_error: number | null;
  sample_count: number | null;
  baseline_mae: number | null;
  baseline_rmse: number | null;
  performance_ratio: number | null;
  computed_at: string | null;
}

export interface VersionComparisonResponse {
  model_name: string;
  versions: VersionComparisonEntry[];
  comparison_period_start: string;
  comparison_period_end: string;
  metrics: string[];
}

async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    signal,
    headers: authHeaders(),
  });

  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(data?.detail ?? `API request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

async function apiPost<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    signal,
    headers: {
      ...authHeaders(),
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(data?.detail ?? `API request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function getPerformanceTimeline(
  modelName: string,
  params?: {
    model_version?: string;
    period_start?: string;
    period_end?: string;
    granularity?: string;
  },
  signal?: AbortSignal,
) {
  const search = new URLSearchParams();
  if (params?.model_version) search.set("model_version", params.model_version);
  if (params?.period_start) search.set("period_start", params.period_start);
  if (params?.period_end) search.set("period_end", params.period_end);
  if (params?.granularity) search.set("granularity", params.granularity);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet<PerformanceTimelineResponse>(
    `/api/v1/models/${encodeURIComponent(modelName)}/monitoring/performance${suffix}`,
    signal,
  );
}

export function getDriftTimeline(
  modelName: string,
  params?: {
    model_version?: string;
    period_start?: string;
    period_end?: string;
    drift_type?: string;
  },
  signal?: AbortSignal,
) {
  const search = new URLSearchParams();
  if (params?.model_version) search.set("model_version", params.model_version);
  if (params?.period_start) search.set("period_start", params.period_start);
  if (params?.period_end) search.set("period_end", params.period_end);
  if (params?.drift_type) search.set("drift_type", params.drift_type);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet<DriftTimelineResponse>(
    `/api/v1/models/${encodeURIComponent(modelName)}/monitoring/drift${suffix}`,
    signal,
  );
}

export function getMonitoringSummary(
  modelName: string,
  model_version?: string,
  signal?: AbortSignal,
) {
  const search = new URLSearchParams();
  if (model_version) search.set("model_version", model_version);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet<MonitoringSummary>(
    `/api/v1/models/${encodeURIComponent(modelName)}/monitoring/summary${suffix}`,
    signal,
  );
}

export function getMonitoringAlerts(
  modelName: string,
  params?: {
    model_version?: string;
    severity?: string;
    limit?: number;
  },
  signal?: AbortSignal,
) {
  const search = new URLSearchParams();
  if (params?.model_version) search.set("model_version", params.model_version);
  if (params?.severity) search.set("severity", params.severity);
  if (params?.limit) search.set("limit", String(params.limit));
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet<MonitoringAlertsResponse>(
    `/api/v1/models/${encodeURIComponent(modelName)}/monitoring/alerts${suffix}`,
    signal,
  );
}

export interface EvaluationResult {
  message: string;
  model_name?: string;
  model_version?: string;
  mae?: number | null;
  rmse?: number | null;
  mape?: number | null;
  sample_count?: number;
  evaluated_models?: Array<{
    model_name: string;
    model_version: string;
    mae: number | null;
    rmse: number | null;
    sample_count: number;
  }>;
}

export interface DriftDetectionResult {
  message: string;
  model_name: string;
  model_version: string;
  drift_reports: Array<{
    drift_type: string;
    feature_name: string | null;
    severity: string;
    drift_score: number;
    is_drifted: boolean;
  }>;
}

export function triggerEvaluation(
  modelName: string,
  params?: {
    model_version?: string;
    period_hours?: number;
  },
  signal?: AbortSignal,
) {
  const search = new URLSearchParams();
  if (params?.model_version) search.set("model_version", params.model_version);
  if (params?.period_hours) search.set("period_hours", String(params.period_hours));
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiPost<EvaluationResult>(
    `/api/v1/models/${encodeURIComponent(modelName)}/monitoring/evaluate${suffix}`,
    signal,
  );
}

export function triggerDriftDetection(
  modelName: string,
  params?: {
    model_version?: string;
    period_hours?: number;
    drift_type?: string;
  },
  signal?: AbortSignal,
) {
  const search = new URLSearchParams();
  if (params?.model_version) search.set("model_version", params.model_version);
  if (params?.period_hours) search.set("period_hours", String(params.period_hours));
  if (params?.drift_type) search.set("drift_type", params.drift_type);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiPost<DriftDetectionResult>(
    `/api/v1/models/${encodeURIComponent(modelName)}/monitoring/drift/detect${suffix}`,
    signal,
  );
}

export function compareVersions(
  modelName: string,
  versionA: string,
  versionB: string,
  params?: {
    period_start?: string;
    period_end?: string;
  },
  signal?: AbortSignal,
) {
  const search = new URLSearchParams({
    version_a: versionA,
    version_b: versionB,
  });
  if (params?.period_start) search.set("period_start", params.period_start);
  if (params?.period_end) search.set("period_end", params.period_end);
  return apiGet<VersionComparisonResponse>(
    `/api/v1/models/${encodeURIComponent(modelName)}/monitoring/compare?${search.toString()}`,
    signal,
  );
}
