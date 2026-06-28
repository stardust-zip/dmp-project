import { authHeaders } from "@/lib/auth-api";
import { API_BASE } from "@/lib/api-base";

// ---------------------------------------------------------------------------
// Domain types
// ---------------------------------------------------------------------------

export interface ExperimentVersionDetail {
  version: string;
  run_id: string;
  model_task: string | null;
  algorithm: string | null;
  hyperparameters: Record<string, string>;
  training_metrics: Record<string, number>;
  training_data_source: string | null;
  training_row_count: number | null;
  training_start: string | null;
  training_end: string | null;
  training_building_count: number | null;
  training_metric_count: number | null;
  feature_count: number | null;
  evaluation_metrics: Record<string, number | null>;
  run_start_time: number | null;
  run_end_time: number | null;
  run_status: string | null;
  current_stage: string | null;
  tags: Record<string, string>;
}

export interface ExperimentComparisonResponse {
  model_name: string;
  versions: ExperimentVersionDetail[];
  comparison_period_start: string;
  comparison_period_end: string;
  common_hyperparameters: string[];
  common_metrics: string[];
}

// ---------------------------------------------------------------------------
// Internal transport helpers
// ---------------------------------------------------------------------------

type ApiErrorPayload = { detail?: unknown };

function extractErrorMessage(detail: unknown): string | null {
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
    return "Backend is unavailable. Confirm the dmp_backend container is running.";
  }
  const data = (await response.json().catch(() => null)) as ApiErrorPayload | null;
  return extractErrorMessage(data?.detail) ?? `API request failed: ${response.status}`;
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

// ---------------------------------------------------------------------------
// Public API functions
// ---------------------------------------------------------------------------

export interface CompareExperimentsParams {
  period_start?: string;
  period_end?: string;
}

/** Compare 2–10 model versions side by side. */
export function compareExperiments(
  modelName: string,
  versions: string[],
  params?: CompareExperimentsParams,
  signal?: AbortSignal,
): Promise<ExperimentComparisonResponse> {
  const search = new URLSearchParams({ versions: versions.join(",") });
  if (params?.period_start) search.set("period_start", params.period_start);
  if (params?.period_end) search.set("period_end", params.period_end);
  return apiGet<ExperimentComparisonResponse>(
    `/api/v1/models/${encodeURIComponent(modelName)}/experiments/compare?${search.toString()}`,
    signal,
  );
}
