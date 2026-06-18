"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/common/icons";
import { Card, Field, Select } from "@/components/common/primitives";
import { displayLocationName, displayModelName, humanizeIdentifier, locationSearchText } from "@/lib/format";
import {
  backfillAnomalyInference,
  cancelPipelineLog,
  demoteModel,
  downloadModelFile,
  getLocationOptions,
  getMetricOptions,
  getModelVersions,
  getPipelineLogs,
  getRegisteredModels,
  rollbackModel,
  trainModel,
  updateModelDescription,
  validateTrainingRequest,
  type AnomalyBackfillPayload,
  type LocationOption,
  type MetricOption,
  type ModelTask,
  type ModelVersion,
  type PipelineLog,
  type RegisteredModel,
  type TrainModelPayload,
  type TrainingValidationResponse,
  type TrainingDataSource,
} from "@/lib/models-api";

const MODEL_TASK_OPTIONS: Array<{ value: ModelTask; label: string }> = [
  { value: "forecasting", label: "Forecasting" },
  { value: "anomaly_detection", label: "Anomaly Detection" },
  { value: "prediction", label: "Prediction" },
];
const MODEL_FILTER_TASK_OPTIONS: Array<{ value: "all" | ModelTask | "unknown"; label: string }> = [
  { value: "all", label: "All Tasks" },
  ...MODEL_TASK_OPTIONS,
  { value: "unknown", label: "Unknown" },
];
const MODEL_STAGE_OPTIONS: Array<{ value: "all" | "production" | "non_production"; label: string }> = [
  { value: "all", label: "All Stages" },
  { value: "production", label: "Production" },
  { value: "non_production", label: "Non-production" },
];

const DATA_SOURCE_OPTIONS: Array<{ value: TrainingDataSource; label: string }> = [
  { value: "csv", label: "Cleaned CSV" },
  { value: "db", label: "Database" },
];

const FORECAST_ALGORITHM_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "xgboost", label: "XGBoost" },
  { value: "lightgbm", label: "LightGBM" },
  { value: "linear_regression", label: "Linear Regression" },
];

const LOCATION_INDEX_LIMIT = 1000;
const MIN_TRAINING_DAYS = 30;

function defaultStartDate() {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() - 30);
  return date.toISOString().slice(0, 10);
}

function defaultEndDate() {
  return new Date().toISOString().slice(0, 10);
}

function isoFromDateInput(value: string, endOfDay = false) {
  return `${value}T${endOfDay ? "23:59:59" : "00:00:00"}Z`;
}

function formatRegistryTime(timestamp?: number | null) {
  if (!timestamp) return "Unknown";
  const millis = timestamp > 10_000_000_000 ? timestamp : timestamp * 1000;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(millis));
}

function formatMetric(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(4);
}

function formatRows(value: number) {
  return new Intl.NumberFormat().format(value);
}

function modelTaskLabel(task: ModelTask | "unknown") {
  if (task === "anomaly_detection") return "Anomaly";
  if (task === "forecasting") return "Forecasting";
  if (task === "prediction") return "Prediction";
  return "Unknown";
}

function inferModelTask(model: RegisteredModel): ModelTask | "unknown" {
  const tags = model.tags ?? {};
  const taggedTask = tags.model_task || tags.task || tags.type;
  if (taggedTask === "prediction" || taggedTask === "forecasting" || taggedTask === "anomaly_detection") return taggedTask;

  const text = `${model.name} ${model.description ?? ""}`.toLowerCase();
  if (text.includes("anomaly")) return "anomaly_detection";
  if (text.includes("forecast")) return "forecasting";
  if (text.includes("prediction") || text.includes("energy_prediction")) return "prediction";
  return "unknown";
}

function inferModelMetric(model: RegisteredModel) {
  const tags = model.tags ?? {};
  const taggedMetric = tags.metric || tags.metric_type || tags.metric_type_id;
  if (taggedMetric) return taggedMetric;

  const energyPrefix = "dmp_energy_prediction_";
  if (model.name.toLowerCase().startsWith(energyPrefix)) {
    const parts = model.name.slice(energyPrefix.length).split("_").filter(Boolean);
    return parts[parts.length - 1] ?? "unknown";
  }
  return "unknown";
}

function modelSearchText(model: RegisteredModel) {
  const task = inferModelTask(model);
  const metric = inferModelMetric(model);
  return [
    model.name,
    displayModelName(model.name),
    model.description ?? "",
    modelTaskLabel(task),
    task,
    metric,
    humanizeIdentifier(metric),
    model.production_version ? "production active live" : "registered non production inactive",
    model.production_version?.version ?? "",
    model.production_version?.current_stage ?? "",
    ...Object.entries(model.tags ?? {}).flatMap(([key, value]) => [key, value]),
  ].join(" ").toLowerCase();
}

function isSuccessfulPipelineLog(log: PipelineLog) {
  return log.status.toLowerCase() === "success" && Boolean(log.mlflow_run_id && log.mlflow_run_id !== "pending");
}

function pipelineDisplayStatus(log: PipelineLog) {
  if (log.status.toLowerCase() === "running" && (!log.mlflow_run_id || log.mlflow_run_id === "pending")) {
    return "Queued";
  }
  return log.status;
}

function pipelineStatusTone(log: PipelineLog) {
  const normalized = pipelineDisplayStatus(log).toLowerCase();
  if (normalized === "success") return "s-green";
  if (normalized === "failed") return "s-red";
  return "s-yellow";
}

function pipelineStatusLabel(log: PipelineLog) {
  return pipelineDisplayStatus(log);
}

function pipelineStatusDescription(log: PipelineLog) {
  const normalized = pipelineDisplayStatus(log).toLowerCase();
  if (normalized === "queued") return "Waiting for a worker to pick up this training job.";
  if (normalized === "running") return "Worker is actively executing this training job.";
  if (normalized === "success") return "Pipeline completed successfully.";
  if (normalized === "failed") return "Pipeline failed. Open details for the terminal log.";
  return log.datasource_used || "Unknown pipeline state.";
}

function pipelineTerminalLog(log: PipelineLog) {
  if (log.terminal_log?.trim()) return log.terminal_log.trim();

  return [
    `[${log.timestamp ? new Date(log.timestamp).toLocaleString() : "unknown time"}] ${log.type} pipeline ${log.status.toLowerCase()}.`,
    `model_task=${log.model_task || "unknown"}`,
    `datasource=${log.datasource_used || "unknown"}`,
    `mlflow_run_id=${log.mlflow_run_id || "-"}`,
    log.execution_time_ms != null ? `execution_time_ms=${log.execution_time_ms}` : "execution_time_ms=-",
    "Detailed terminal output was not captured for this older run.",
  ].join("\n");
}

function TrainingValidationPanel({
  dataSource,
  validation,
  loading,
  error,
}: {
  dataSource: TrainingDataSource;
  validation: TrainingValidationResponse | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <div className="training-validation is-loading">
        <Icon name="refresh" className="spin" />
        <span>Checking metric availability, telemetry range, and training row counts...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="training-validation is-invalid">
        <Icon name="alert" />
        <span>{error}</span>
      </div>
    );
  }

  if (!validation) {
    return (
      <div className="training-validation">
        <Icon name="info" />
        <span>Select a location, metric, and date range to validate training data.</span>
      </div>
    );
  }

  const sourceLabel = dataSource === "csv" ? "CSV" : "Database";

  return (
    <div className={`training-validation ${validation.valid ? "is-valid" : "is-invalid"}`}>
      <div className="training-validation-head">
        <span className="training-validation-icon">
          <Icon name={validation.valid ? "check" : "alert"} />
        </span>
        <div>
          <b>{validation.valid ? "Training data is ready" : "Training data needs attention"}</b>
          <span>
            {validation.target_building_ids.length
              ? `${validation.target_building_ids.length} building(s), minimum ${validation.required_rows_per_metric} rows per metric from ${sourceLabel}.`
              : "No target buildings resolved for this request."}
          </span>
        </div>
      </div>

      {validation.errors.length > 0 && (
        <div className="training-validation-list">
          {validation.errors.slice(0, 4).map((message) => (
            <span key={message}>{message}</span>
          ))}
        </div>
      )}

      {validation.metrics.length > 0 && (
        <div className="training-metric-grid">
          {validation.metrics.map((metric) => (
            <div className={metric.enough_rows ? "is-ok" : "is-bad"} key={metric.metric}>
              <b>{metric.metric}</b>
              <span>
                <small>DB</small>
                {formatRows(metric.db_rows)}
              </span>
              <span>
                <small>CSV</small>
                {formatRows(metric.csv_rows)}
              </span>
              <span>
                <small>Status</small>
                {metric.enough_rows ? "Enough rows" : `Needs ${formatRows(metric.required_rows)}`}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ModelsPage() {
  const locationPickerRef = useRef<HTMLDivElement | null>(null);
  const terminalLogRef = useRef<HTMLPreElement | null>(null);
  const registryRefreshRunIdsRef = useRef<Set<string>>(new Set());
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [logs, setLogs] = useState<PipelineLog[]>([]);
  const [locationOptions, setLocationOptions] = useState<LocationOption[]>([]);
  const [metricOptions, setMetricOptions] = useState<MetricOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [logsLoading, setLogsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modelTask, setModelTask] = useState<ModelTask>("prediction");
  const [dataSource, setDataSource] = useState<TrainingDataSource>("csv");
  const [forecastAlgorithm, setForecastAlgorithm] = useState("xgboost");
  const [forecastHorizon, setForecastHorizon] = useState(24);
  const [locationId, setLocationId] = useState("");
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>([]);
  const [locationQuery, setLocationQuery] = useState("");
  const [metricQuery, setMetricQuery] = useState("");
  const [startDate, setStartDate] = useState(defaultStartDate);
  const [endDate, setEndDate] = useState(defaultEndDate);
  const [submitting, setSubmitting] = useState(false);
  const [rollbackSubmitting, setRollbackSubmitting] = useState(false);
  const [demoteSubmitting, setDemoteSubmitting] = useState(false);
  const [downloadSubmitting, setDownloadSubmitting] = useState(false);
  const [selectedModelName, setSelectedModelName] = useState("");
  const [versions, setVersions] = useState<ModelVersion[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionError, setVersionError] = useState<string | null>(null);
  const [trainingValidation, setTrainingValidation] = useState<TrainingValidationResponse | null>(null);
  const [validationLoading, setValidationLoading] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [trainMessage, setTrainMessage] = useState<string | null>(null);
  const [locationPickerOpen, setLocationPickerOpen] = useState(false);
  const [locationSearchLoading, setLocationSearchLoading] = useState(false);
  const [detailModelName, setDetailModelName] = useState<string | null>(null);
  const [trainModalOpen, setTrainModalOpen] = useState(false);
  const [pipelineModalOpen, setPipelineModalOpen] = useState(false);
  const [detailLog, setDetailLog] = useState<PipelineLog | null>(null);
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [descriptionSubmitting, setDescriptionSubmitting] = useState(false);
  const [cancelSubmitting, setCancelSubmitting] = useState(false);
  const [modelQuery, setModelQuery] = useState("");
  const [modelTaskFilter, setModelTaskFilter] = useState<"all" | ModelTask | "unknown">("all");
  const [modelStageFilter, setModelStageFilter] = useState<"all" | "production" | "non_production">("all");
  const [modelMetricFilter, setModelMetricFilter] = useState("all");
  const [backfillModalOpen, setBackfillModalOpen] = useState(false);
  const [backfillStartDate, setBackfillStartDate] = useState("2017-10-01");
  const [backfillEndDate, setBackfillEndDate] = useState("2017-12-31");
  const [backfillSubmitting, setBackfillSubmitting] = useState(false);

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      setLoading(true);
      setError(null);

      try {
        const [modelData, logData, locationData, metricData] = await Promise.all([
          getRegisteredModels(controller.signal),
          getPipelineLogs(controller.signal),
          getLocationOptions({ limit: LOCATION_INDEX_LIMIT }, controller.signal),
          getMetricOptions(controller.signal),
        ]);
        setModels(modelData.models);
        setLogs(logData.logs);
        registryRefreshRunIdsRef.current = new Set(
          logData.logs.filter(isSuccessfulPipelineLog).map((log) => log.mlflow_run_id as string),
        );
        setSelectedModelName((current) => current || modelData.models[0]?.name || "");
        setLocationOptions(locationData.locations);
        setMetricOptions(metricData.metrics);
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : "Unable to load AI engineering data.");
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          setLogsLoading(false);
        }
      }
    }

    void load();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!locationPickerOpen) return;

    const closeIfOutside = (event: PointerEvent) => {
      if (!locationPickerRef.current?.contains(event.target as Node)) {
        setLocationPickerOpen(false);
      }
    };

    document.addEventListener("pointerdown", closeIfOutside);
    return () => document.removeEventListener("pointerdown", closeIfOutside);
  }, [locationPickerOpen]);

  useEffect(() => {
    if (!detailModelName) return;

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDetailModelName(null);
    };

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [detailModelName]);

  const refreshRegistry = useCallback(
    async (signal?: AbortSignal) => {
      const modelData = await getRegisteredModels(signal);
      setModels(modelData.models);
      setSelectedModelName((current) => current || modelData.models[0]?.name || "");

      if (selectedModelName && modelData.models.some((model) => model.name === selectedModelName)) {
        const versionData = await getModelVersions(selectedModelName, signal);
        setVersions(versionData.versions);
        setSelectedRunId((current) =>
          versionData.versions.some((version) => version.run_id === current) ? current : versionData.versions[0]?.run_id || "",
        );
      }

      return modelData.models;
    },
    [selectedModelName],
  );

  const refreshLogs = useCallback(
    async (signal?: AbortSignal) => {
      const logData = await getPipelineLogs(signal);
      setLogs(logData.logs);
      setDetailLog((current) => (current ? logData.logs.find((log) => log.id === current.id) ?? current : current));

      const successfulRunIds = logData.logs
        .filter(isSuccessfulPipelineLog)
        .map((log) => log.mlflow_run_id as string);
      const hasNewSuccessfulRun = successfulRunIds.some((runId) => !registryRefreshRunIdsRef.current.has(runId));
      successfulRunIds.forEach((runId) => registryRefreshRunIdsRef.current.add(runId));

      if (hasNewSuccessfulRun) {
        await refreshRegistry(signal);
      }

      return logData.logs;
    },
    [refreshRegistry],
  );

  useEffect(() => {
    if (!pipelineModalOpen && !detailLog && !submitting) return;

    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      void refreshLogs(controller.signal).catch(() => { });
    }, 0);
    const interval = window.setInterval(() => {
      void refreshLogs(controller.signal).catch(() => { });
    }, 2000);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
      window.clearInterval(interval);
    };
  }, [detailLog, pipelineModalOpen, refreshLogs, submitting]);

  useEffect(() => {
    const controller = new AbortController();

    async function loadVersions() {
      if (!selectedModelName) {
        setVersions([]);
        setSelectedRunId("");
        setVersionError(null);
        return;
      }

      setVersionsLoading(true);
      setVersionError(null);
      try {
        const data = await getModelVersions(selectedModelName, controller.signal);
        setVersions(data.versions);
        setSelectedRunId((current) => (data.versions.some((version) => version.run_id === current) ? current : data.versions[0]?.run_id || ""));
      } catch (err) {
        if (!controller.signal.aborted) {
          setVersions([]);
          setSelectedRunId("");
          setVersionError(err instanceof Error ? err.message : "Unable to load model versions.");
        }
      } finally {
        if (!controller.signal.aborted) {
          setVersionsLoading(false);
        }
      }
    }

    void loadVersions();
    return () => controller.abort();
  }, [selectedModelName]);

  const filteredMetrics = metricOptions
    .filter((metric) => `${metric.id} ${metric.description ?? ""}`.toLowerCase().includes(metricQuery.toLowerCase()))
    .slice(0, 8);
  const locationById = useMemo(() => new Map(locationOptions.map((location) => [location.id, location])), [locationOptions]);
  const filteredLocationOptions = useMemo(() => {
    const query = locationQuery.trim().toLowerCase();
    return locationOptions
      .filter((location) => !query || locationSearchText(location, location.parent_id ? locationById.get(location.parent_id) : null).includes(query))
      .slice(0, 12);
  }, [locationById, locationOptions, locationQuery]);
  const detailModel = models.find((model) => model.name === detailModelName) ?? null;
  const modelMetricOptions = useMemo(() => {
    const metrics = [...new Set(models.map(inferModelMetric).filter((metric) => metric && metric !== "unknown"))].sort((left, right) => left.localeCompare(right));
    return [{ value: "all", label: "All Metrics" }, ...metrics.map((metric) => ({ value: metric, label: humanizeIdentifier(metric) }))];
  }, [models]);
  const filteredModels = useMemo(() => {
    const query = modelQuery.trim().toLowerCase();
    return models.filter((model) => {
      const task = inferModelTask(model);
      const metric = inferModelMetric(model);
      if (modelTaskFilter !== "all" && task !== modelTaskFilter) return false;
      if (modelStageFilter === "production" && !model.production_version) return false;
      if (modelStageFilter === "non_production" && model.production_version) return false;
      if (modelMetricFilter !== "all" && metric !== modelMetricFilter) return false;
      return !query || modelSearchText(model).includes(query);
    });
  }, [modelMetricFilter, modelQuery, modelStageFilter, modelTaskFilter, models]);
  const selectedVersion = versions.find((version) => version.run_id === selectedRunId) ?? null;
  const detailVersion = detailModelName === selectedModelName ? selectedVersion : null;
  const detailVersions = detailModelName === selectedModelName ? versions : [];
  const detailVersionIsProduction = Boolean(
    detailModel?.production_version?.run_id && detailVersion?.run_id && detailModel.production_version.run_id === detailVersion.run_id,
  );
  const detailVersionMetricEntries = Object.entries(detailVersion?.metrics ?? {}).sort(([left], [right]) => left.localeCompare(right));
  const detailVersionTagEntries = Object.entries(detailVersion?.tags ?? {}).sort(([left], [right]) => left.localeCompare(right));
  const pipelineLogsByRunId = useMemo(() => {
    const byRunId = new Map<string, PipelineLog[]>();
    logs.forEach((log) => {
      if (!log.mlflow_run_id || log.mlflow_run_id === "pending") return;
      const runLogs = byRunId.get(log.mlflow_run_id) ?? [];
      runLogs.push(log);
      byRunId.set(log.mlflow_run_id, runLogs);
    });
    return byRunId;
  }, [logs]);
  const detailVersionPipelineLogs = detailVersions.flatMap((version) =>
    (pipelineLogsByRunId.get(version.run_id) ?? []).map((log) => ({ version, log })),
  );
  const detailTerminalLog = detailLog ? pipelineTerminalLog(detailLog) : "";
  const selectedMetricsKey = selectedMetrics.join(",");
  const selectedTaskLabel = MODEL_TASK_OPTIONS.find((option) => option.value === modelTask)?.label ?? modelTask;
  const trainingTaskImplemented =
    modelTask === "prediction" || modelTask === "anomaly_detection" || modelTask === "forecasting";
  const metricSelectionValid =
    modelTask === "prediction" || modelTask === "forecasting" ? selectedMetrics.length === 1 : true;
  const isAnomalyDetection = modelTask === "anomaly_detection";
  const isForecasting = modelTask === "forecasting";
  const validationInputReady = isAnomalyDetection
    ? Boolean(startDate && endDate)
    : Boolean(locationId.trim() && selectedMetrics.length && startDate && endDate);
  const dateRangeDays = startDate && endDate
    ? Math.round((new Date(endDate).getTime() - new Date(startDate).getTime()) / 86_400_000)
    : 0;
  const dateRangeValid = dateRangeDays >= MIN_TRAINING_DAYS;
  const trainingPayload = useMemo<TrainModelPayload>(
    () => ({
      site_id: isAnomalyDetection ? null : locationId.trim(),
      metrics: isAnomalyDetection ? ["electricity"] : selectedMetrics,
      time_range_start: isoFromDateInput(startDate),
      time_range_end: isoFromDateInput(endDate, true),
      model_task: modelTask,
      data_source: dataSource,
      ...(isForecasting
        ? { algorithm: forecastAlgorithm, forecast_horizon_hours: forecastHorizon }
        : {}),
    }),
    [
      dataSource,
      endDate,
      forecastAlgorithm,
      forecastHorizon,
      isAnomalyDetection,
      isForecasting,
      locationId,
      modelTask,
      selectedMetrics,
      startDate,
    ],
  );
  const canTrain = trainingTaskImplemented && metricSelectionValid && validationInputReady && dateRangeValid && !submitting && !validationLoading && trainingValidation?.valid !== false;

  useEffect(() => {
    if (!terminalLogRef.current) return;
    terminalLogRef.current.scrollTop = terminalLogRef.current.scrollHeight;
  }, [detailTerminalLog]);

  useEffect(() => {
    if (!trainModalOpen) return;

    const query = locationQuery.trim();
    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      setLocationSearchLoading(true);
      try {
        const data = await getLocationOptions({ q: query || undefined, limit: LOCATION_INDEX_LIMIT }, controller.signal);
        setLocationOptions(data.locations);
      } catch {
        if (!controller.signal.aborted) setLocationOptions([]);
      } finally {
        if (!controller.signal.aborted) setLocationSearchLoading(false);
      }
    }, query ? 180 : 0);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [locationQuery, trainModalOpen]);

  useEffect(() => {
    if (!trainModalOpen || !trainingTaskImplemented || !metricSelectionValid || !validationInputReady || isAnomalyDetection) {
      const timeout = window.setTimeout(() => {
        setTrainingValidation(null);
        setValidationError(null);
        setValidationLoading(false);
      }, 0);
      return () => window.clearTimeout(timeout);
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      setValidationLoading(true);
      setValidationError(null);

      try {
        const validation = await validateTrainingRequest(trainingPayload, controller.signal);
        setTrainingValidation(validation);
      } catch (err) {
        if (!controller.signal.aborted) {
          setTrainingValidation(null);
          setValidationError(err instanceof Error ? err.message : "Unable to validate training data.");
        }
      } finally {
        if (!controller.signal.aborted) {
          setValidationLoading(false);
        }
      }
    }, 350);

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [isAnomalyDetection, metricSelectionValid, selectedMetricsKey, trainModalOpen, trainingPayload, trainingTaskImplemented, validationInputReady]);

  function chooseLocation(location: LocationOption) {
    setLocationId(location.id);
    setLocationQuery(displayLocationName(location.name, location.id));
    setLocationPickerOpen(false);
  }

  function toggleMetric(metricId: string) {
    setSelectedMetrics((current) => (current.includes(metricId) ? current.filter((metric) => metric !== metricId) : [...current, metricId]));
  }

  function openModelDetails(modelName: string) {
    const model = models.find((item) => item.name === modelName);
    setSelectedModelName(modelName);
    setDetailModelName(modelName);
    setDescriptionDraft(model?.description ?? "");
  }

  async function onTrainModel() {
    if (!trainingTaskImplemented) {
      setError(`${selectedTaskLabel} training pipeline is not implemented yet.`);
      return;
    }

    if (!isAnomalyDetection) {
      const resolvedLocationId = locationId.trim();
      const knownMetricIds = new Set(metricOptions.map((metric) => metric.id));
      const invalidMetrics = selectedMetrics.filter((metric) => !knownMetricIds.has(metric));

      if (!resolvedLocationId) {
        setError("Select a location from the search results before training.");
        return;
      }

      if (!selectedMetrics.length) {
        setError("At least one metric is required.");
        return;
      }

      if (!metricSelectionValid) {
        setError("Prediction training requires exactly one metric per model.");
        return;
      }

      if (invalidMetrics.length) {
        setError(`Unknown metric(s): ${invalidMetrics.join(", ")}`);
        return;
      }
    }

    setSubmitting(true);
    setError(null);
    setTrainMessage(null);

    try {
      if (!isAnomalyDetection) {
        const validation = await validateTrainingRequest(trainingPayload);
        setTrainingValidation(validation);

        if (!validation.valid) {
          setError("Training data is not valid. Review the validation details below.");
          return;
        }
      }

      const response = await trainModel(trainingPayload);
      setTrainMessage(`${response.message} Task ${response.task_id} queued.`);
      setTrainModalOpen(false);
      setPipelineModalOpen(true);
      await refreshLogs();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to start training.");
    } finally {
      setSubmitting(false);
    }
  }

  async function onRollbackModel() {
    if (!selectedModelName || !selectedRunId) {
      setError("Select a model version before rollback.");
      return;
    }

    setRollbackSubmitting(true);
    setError(null);
    setTrainMessage(null);

    try {
      const response = await rollbackModel({
        model_name: selectedModelName,
        mlflow_run_id: selectedRunId,
      });
      setTrainMessage(`${response.model_name} v${response.version} promoted to production.`);
      const modelData = await getRegisteredModels();
      setModels(modelData.models);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to rollback model.");
    } finally {
      setRollbackSubmitting(false);
    }
  }

  async function onDemoteModel() {
    if (!selectedModelName || !selectedRunId) {
      setError("Select a production model version before removing it from production.");
      return;
    }

    setDemoteSubmitting(true);
    setError(null);
    setTrainMessage(null);

    try {
      const response = await demoteModel({
        model_name: selectedModelName,
        mlflow_run_id: selectedRunId,
      });
      setTrainMessage(`${response.model_name} v${response.version} moved out of production.`);
      const [modelData, versionData] = await Promise.all([
        getRegisteredModels(),
        getModelVersions(selectedModelName),
      ]);
      setModels(modelData.models);
      setVersions(versionData.versions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to move model out of production.");
    } finally {
      setDemoteSubmitting(false);
    }
  }

  function onDownloadModel() {
    if (!selectedModelName || !selectedRunId) {
      setError("Select a model version before downloading.");
      return;
    }

    const version = versions.find((v) => v.run_id === selectedRunId);
    if (!version) {
      setError("Selected version not found in registry.");
      return;
    }

    setDownloadSubmitting(true);
    setError(null);
    downloadModelFile(selectedModelName, version.version)
      .then(({ blob, filename }) => {
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        URL.revokeObjectURL(url);
        setTrainMessage(`${filename} downloaded.`);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Unable to download model.");
      })
      .finally(() => {
        setDownloadSubmitting(false);
      });
  }

  async function onCancelPipeline(log: PipelineLog) {
    setCancelSubmitting(true);
    setError(null);
    try {
      await cancelPipelineLog(log.id);
      await refreshLogs();
      setDetailLog((current) => (current?.id === log.id ? { ...current, status: "Cancelled" } : current));
      setTrainMessage("Pipeline cancelled.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to cancel pipeline.");
    } finally {
      setCancelSubmitting(false);
    }
  }

  async function onBackfillInference() {
    setBackfillSubmitting(true);
    setError(null);
    setTrainMessage(null);

    try {
      const payload: AnomalyBackfillPayload = {
        time_range_start: isoFromDateInput(backfillStartDate),
        time_range_end: isoFromDateInput(backfillEndDate, true),
      };
      const response = await backfillAnomalyInference(payload);
      setTrainMessage(`${response.message} Task ${response.task_id} queued.`);
      setBackfillModalOpen(false);
      setPipelineModalOpen(true);
      await refreshLogs();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to start backfill inference.");
    } finally {
      setBackfillSubmitting(false);
    }
  }

  async function onSaveModelDescription() {
    if (!detailModel) return;

    setDescriptionSubmitting(true);
    setError(null);
    setTrainMessage(null);
    try {
      const response = await updateModelDescription(detailModel.name, { description: descriptionDraft });
      setModels((current) => current.map((model) => (model.name === response.name ? { ...model, description: response.description } : model)));
      setDescriptionDraft(response.description);
      setTrainMessage(`${displayModelName(detailModel.name)} description updated.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update model description.");
    } finally {
      setDescriptionSubmitting(false);
    }
  }

  return (
    <main className="page models-page">
      <div className="page-head models-head">
        <div>
          <h1 className="page-title">AI Engineering</h1>
          <p className="page-sub">Registered models, production status, and recent pipeline activity.</p>
        </div>
        <div className="page-head-actions model-primary-actions">
          <button className="btn" type="button" onClick={() => setPipelineModalOpen(true)}>
            <Icon name="table" />
            <span>Pipeline</span>
          </button>
          <button className="btn" type="button" onClick={() => setBackfillModalOpen(true)}>
            <Icon name="refresh" />
            <span>Backfill Inference</span>
          </button>
          <button className="btn btn-primary" type="button" onClick={() => setTrainModalOpen(true)}>
            <Icon name="spark2" />
            <span>Train Model</span>
          </button>
        </div>
      </div>

      {error && <div className="anomaly-error">{error}</div>}
      {trainMessage && <div className="models-success">{trainMessage}</div>}

      <div className="models-single-layout">
        <Card title="All Models" sub={loading ? "Loading registry..." : `${filteredModels.length} of ${models.length} registered models`} icon="cpu">
          <div className="model-registry-toolbar">
            <div className="model-registry-search">
              <Icon name="search" />
              <input
                value={modelQuery}
                onChange={(event) => setModelQuery(event.target.value)}
                placeholder="Search model, task, metric, description, tag, or raw ID"
              />
            </div>
            <Select value={modelTaskFilter} onChange={setModelTaskFilter} options={MODEL_FILTER_TASK_OPTIONS} />
            <Select value={modelStageFilter} onChange={setModelStageFilter} options={MODEL_STAGE_OPTIONS} />
            <Select value={modelMetricFilter} onChange={setModelMetricFilter} options={modelMetricOptions} searchable />
          </div>
          {loading ? (
            <div className="empty">Loading models...</div>
          ) : filteredModels.length ? (
            <div className="model-list model-gallery">
              {filteredModels.map((model) => {
                const task = inferModelTask(model);
                const metric = inferModelMetric(model);
                return (
                  <button
                    className={`model-row model-row-${task.replace("_", "-")} ${model.production_version ? "is-production" : "is-non-production"} ${selectedModelName === model.name ? "is-selected" : ""}`}
                    key={model.name}
                    type="button"
                    onClick={() => openModelDetails(model.name)}
                  >
                    <div className="model-card-top">
                      <b title={model.name}>{displayModelName(model.name)}</b>
                    </div>
                    <span className="model-card-description">{model.description || "No description"}</span>
                    <div className="model-card-detail-grid">
                      <span className="model-detail-metric">
                        <small>Metric</small>
                        {humanizeIdentifier(metric)}
                      </span>
                      <span className={`model-detail-production ${model.production_version ? "has-production" : "no-production"}`}>
                        <small>Production</small>
                        {model.production_version ? `v${model.production_version.version}` : "None"}
                      </span>
                      <span className="model-detail-versions">
                        <small>Versions</small>
                        {model.latest_versions.length}
                      </span>
                      <span className="model-detail-updated">
                        <small>Updated</small>
                        {formatRegistryTime(model.last_updated_timestamp)}
                      </span>
                    </div>
                    <div className="model-version-stack">
                      <span className={`model-task-chip task-${task.replace("_", "-")}`}>{modelTaskLabel(task)}</span>
                      <span className={`model-stage-chip ${model.production_version ? "is-production" : "is-non-production"}`}>
                        {model.production_version ? "Production" : "Non-production"}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="empty">No models match the selected search and filters.</div>
          )}
        </Card>
      </div>

      {backfillModalOpen && (
        <>
          <button className="overlay" type="button" aria-label="Close backfill dialog" onClick={() => setBackfillModalOpen(false)} />
          <div className="model-modal train-model-modal" role="dialog" aria-modal="true" aria-label="Backfill inference">
            <div className="model-modal-head">
              <div>
                <h2>Backfill Inference</h2>
                <span>Score rule-based and LGBm anomalies for a historical date range and save to DB.</span>
              </div>
              <button className="icon-btn" type="button" aria-label="Close backfill dialog" onClick={() => setBackfillModalOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="model-modal-body">
              <div className="train-model-form">
                <Field label="Date range">
                  <div className="date-range-row">
                    <div className="date-range-segment">
                      <Icon name="calendar" />
                      <div className="date-range-segment-body">
                        <span>From</span>
                        <input type="date" value={backfillStartDate} onChange={(event) => setBackfillStartDate(event.target.value)} />
                      </div>
                    </div>
                    <div className="date-range-segment">
                      <Icon name="calendar" />
                      <div className="date-range-segment-body">
                        <span>To</span>
                        <input type="date" value={backfillEndDate} onChange={(event) => setBackfillEndDate(event.target.value)} />
                      </div>
                    </div>
                  </div>
                </Field>
              </div>
              <div className="training-validation">
                <Icon name="info" />
                <span>
                  Requires a production anomaly detection model in MLflow. Rule-based checks run once
                  over the full range; LGBm inference runs hour by hour. Results are saved to the DB
                  and will appear in the Anomaly Detection simulator.
                </span>
              </div>
            </div>
            <div className="model-modal-foot">
              <button className="btn" type="button" onClick={() => setBackfillModalOpen(false)}>
                <Icon name="x" />
                <span>Cancel</span>
              </button>
              <button
                className="btn btn-primary"
                type="button"
                onClick={onBackfillInference}
                disabled={backfillSubmitting || !backfillStartDate || !backfillEndDate || backfillEndDate <= backfillStartDate}
              >
                <Icon name={backfillSubmitting ? "refresh" : "play"} className={backfillSubmitting ? "spin" : undefined} />
                <span>{backfillSubmitting ? "Queueing..." : "Run Backfill"}</span>
              </button>
            </div>
          </div>
        </>
      )}

      {trainModalOpen && (
        <>
          <button className="overlay" type="button" aria-label="Close train model dialog" onClick={() => setTrainModalOpen(false)} />
          <div className="model-modal train-model-modal" role="dialog" aria-modal="true" aria-label="Train model">
            <div className="model-modal-head">
              <div>
                <h2>Train Model</h2>
                <span>Queue a new ML pipeline run after validating source data.</span>
              </div>
              <button className="icon-btn" type="button" aria-label="Close train model dialog" onClick={() => setTrainModalOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="model-modal-body">
              <div className="train-model-form">
                <Field label="Task">
                  <Select value={modelTask} onChange={setModelTask} options={MODEL_TASK_OPTIONS} />
                </Field>
                <Field label="Data source">
                  <Select value={dataSource} onChange={setDataSource} options={DATA_SOURCE_OPTIONS} />
                </Field>
                {!isAnomalyDetection && (
                  <Field label="Location">
                    <div className="model-combobox" ref={locationPickerRef}>
                      <input
                        className="input"
                        value={locationQuery}
                        onFocus={() => setLocationPickerOpen(true)}
                        onChange={(event) => {
                          setLocationQuery(event.target.value);
                          setLocationId("");
                          setLocationPickerOpen(true);
                        }}
                        placeholder="Search site or building by name or ID"
                      />
                      {locationPickerOpen && (
                        <div className="model-picker-list">
                          {locationSearchLoading ? (
                            <div className="model-picker-empty">Searching locations...</div>
                          ) : filteredLocationOptions.length ? (
                            filteredLocationOptions.map((location) => (
                              <button key={location.id} type="button" onClick={() => chooseLocation(location)}>
                                <b title={location.id}>{displayLocationName(location.name, location.id)}</b>
                                <span title={location.id}>
                                  {location.parent_id ? `Site ${location.parent_id} · ` : ""}{location.id}
                                </span>
                              </button>
                            ))
                          ) : (
                            <div className="model-picker-empty">No locations found.</div>
                          )}
                        </div>
                      )}
                    </div>
                  </Field>
                )}
                {!isAnomalyDetection && (
                  <Field label="Metrics">
                    <input className="input" value={metricQuery} onChange={(event) => setMetricQuery(event.target.value)} placeholder="Choose one metric for prediction training" />
                    <div className="metric-choice-list">
                      {filteredMetrics.map((metric) => (
                        <button key={metric.id} type="button" className={selectedMetrics.includes(metric.id) ? "is-selected" : ""} onClick={() => toggleMetric(metric.id)}>
                          {humanizeIdentifier(metric.id)}
                        </button>
                      ))}
                    </div>
                    <div className="metric-chip-list">
                      {selectedMetrics.map((metric) => (
                        <button key={metric} type="button" onClick={() => toggleMetric(metric)}>
                          {humanizeIdentifier(metric)}
                          <Icon name="x" />
                        </button>
                      ))}
                    </div>
                  </Field>
                )}
                <Field label="Date range">
                  <div className={`date-range-row${startDate && endDate && !dateRangeValid ? " is-invalid" : ""}`}>
                    <div className="date-range-segment">
                      <Icon name="calendar" />
                      <div className="date-range-segment-body">
                        <span>From</span>
                        <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
                      </div>
                    </div>
                    <div className="date-range-segment">
                      <Icon name="calendar" />
                      <div className="date-range-segment-body">
                        <span>To</span>
                        <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
                      </div>
                    </div>
                  </div>
                  {startDate && endDate && !dateRangeValid && (
                    <span className="date-range-error">
                      <Icon name="alert" />
                      Minimum {MIN_TRAINING_DAYS} days required ({dateRangeDays} selected).
                    </span>
                  )}
                </Field>
                {isForecasting && (
                  <>
                    <Field label="Algorithm">
                      <Select value={forecastAlgorithm} onChange={setForecastAlgorithm} options={FORECAST_ALGORITHM_OPTIONS} />
                    </Field>
                    <Field label="Forecast horizon (hours)">
                      <input
                        className="input"
                        type="number"
                        min={1}
                        max={168}
                        value={forecastHorizon}
                        onChange={(event) =>
                          setForecastHorizon(
                            Math.max(1, Math.min(168, Number(event.target.value) || 24)),
                          )
                        }
                      />
                    </Field>
                  </>
                )}
              </div>
              {!trainingTaskImplemented ? (
                <div className="training-validation is-invalid">
                  <Icon name="alert" />
                  <span>{selectedTaskLabel} training pipeline is not implemented yet.</span>
                </div>
              ) : isAnomalyDetection ? (
                <div className="training-validation">
                  <Icon name="info" />
                  <span>Trains across all buildings using electricity data. Select a date range to proceed.</span>
                </div>
              ) : !metricSelectionValid ? (
                <div className="training-validation is-invalid">
                  <Icon name="alert" />
                  <span>{selectedTaskLabel} training requires exactly one metric per model.</span>
                </div>
              ) : (
                <TrainingValidationPanel
                  dataSource={dataSource}
                  validation={validationInputReady ? trainingValidation : null}
                  loading={validationInputReady && validationLoading}
                  error={validationInputReady ? validationError : null}
                />
              )}
            </div>
            <div className="model-modal-foot">
              <button className="btn" type="button" onClick={() => setTrainModalOpen(false)}>
                <Icon name="x" />
                <span>Cancel</span>
              </button>
              <button className="btn btn-primary" type="button" onClick={onTrainModel} disabled={!canTrain}>
                <Icon name={submitting ? "refresh" : "plus"} className={submitting ? "spin" : undefined} />
                <span>{!trainingTaskImplemented ? "Not Implemented" : submitting ? "Queueing..." : "Train Model"}</span>
              </button>
            </div>
          </div>
        </>
      )}

      {pipelineModalOpen && (
        <>
          <button className="overlay" type="button" aria-label="Close pipeline activity" onClick={() => setPipelineModalOpen(false)} />
          <div className="model-modal pipeline-modal" role="dialog" aria-modal="true" aria-label="Pipeline activity">
            <div className="model-modal-head">
              <div>
                <h2>Pipeline Activity</h2>
                <span>{logsLoading ? "Loading runs..." : `${logs.length} recent runs`}</span>
              </div>
              <button className="icon-btn" type="button" aria-label="Close pipeline activity" onClick={() => setPipelineModalOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="model-modal-body">
              {logsLoading ? (
                <div className="empty">Loading pipeline logs...</div>
              ) : logs.length ? (
                <div className="model-log-list">
                  {logs.map((log) => (
                    <button
                      className="model-log-row"
                      key={log.id}
                      type="button"
                      onClick={() => { setPipelineModalOpen(false); setDetailLog(log); }}
                    >
                      <span className={`status-dot ${pipelineStatusTone(log)}`} />
                      <div>
                        <b>{log.model_task || log.type}</b>
                        <span className="model-log-source" title={log.datasource_used || "Unknown datasource"}>
                          {pipelineStatusDescription(log)}
                        </span>
                      </div>
                      <span className="badge badge-neutral">{pipelineStatusLabel(log)}</span>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="empty">No pipeline logs found.</div>
              )}
            </div>
          </div>
        </>
      )}

      {detailLog && (
        <>
          <button className="overlay" type="button" aria-label="Close pipeline log details" onClick={() => setDetailLog(null)} />
          <div className="model-modal pipeline-log-modal" role="dialog" aria-modal="true" aria-label="Pipeline log details">
            <div className="model-modal-head">
              <div>
                <h2>Pipeline Log Details</h2>
                <span>Run {detailLog.id.slice(0, 8)} &mdash; {detailLog.model_task || detailLog.type}</span>
              </div>
              <button className="icon-btn" type="button" aria-label="Close pipeline log details" onClick={() => setDetailLog(null)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="model-modal-body">
              <div className="pipeline-log-summary">
                <span className={`status-dot ${pipelineStatusTone(detailLog)}`} />
                <div>
                  <b>{detailLog.model_task || detailLog.type}</b>
                  <span style={{ color: detailLog.status === "Success" ? "var(--green)" : detailLog.status === "Failed" ? "var(--red)" : "var(--amber)", fontWeight: 600 }}>
                    {pipelineStatusLabel(detailLog)}
                  </span>
                  <span>{pipelineStatusDescription(detailLog)}</span>
                </div>
              </div>

              <div className="model-section-title">Run Details</div>
              <div className="model-detail-grid">
                <div>
                  <span>Run ID</span>
                  <b className="mono" title={detailLog.id}>{detailLog.id}</b>
                </div>
                <div>
                  <span>Type</span>
                  <b>{detailLog.type}</b>
                </div>
                <div>
                  <span>Model Task</span>
                  <b>{detailLog.model_task || "Unknown"}</b>
                </div>
                <div>
                  <span>Status</span>
                  <b style={{ color: detailLog.status === "Success" ? "var(--green)" : detailLog.status === "Failed" ? "var(--red)" : "var(--amber)" }}>{pipelineStatusLabel(detailLog)}</b>
                </div>
                <div>
                  <span>Execution Time</span>
                  <b>{detailLog.execution_time_ms != null ? `${(detailLog.execution_time_ms / 1000).toFixed(1)}s` : "-"}</b>
                </div>
                <div>
                  <span>Data Source</span>
                  <b>{detailLog.datasource_used || "Unknown"}</b>
                </div>
                <div>
                  <span>MLflow Run ID</span>
                  <b className="mono" title={detailLog.mlflow_run_id || ""}>{detailLog.mlflow_run_id || "-"}</b>
                </div>
                <div>
                  <span>Timestamp</span>
                  <b>{detailLog.timestamp ? new Date(detailLog.timestamp).toLocaleString() : "-"}</b>
                </div>
              </div>
              <div className="model-section-title">Terminal Log</div>
              <pre ref={terminalLogRef} className="pipeline-terminal-log">{detailTerminalLog}</pre>
            </div>
            {["Running", "running"].includes(pipelineDisplayStatus(detailLog)) && (
              <div className="model-modal-foot">
                <button
                  className="btn btn-danger"
                  type="button"
                  onClick={() => onCancelPipeline(detailLog)}
                  disabled={cancelSubmitting}
                >
                  <Icon name={cancelSubmitting ? "refresh" : "x"} className={cancelSubmitting ? "spin" : undefined} />
                  <span>{cancelSubmitting ? "Cancelling..." : "Cancel Pipeline"}</span>
                </button>
              </div>
            )}
          </div>
        </>
      )}

      {detailModel && (
        <>
          <button className="overlay" type="button" aria-label="Close model details" onClick={() => setDetailModelName(null)} />
          <div className="model-modal" role="dialog" aria-label={`${detailModel.name} details`}>
            <div className="model-modal-head">
              <div>
                <h2 title={detailModel.name}>{displayModelName(detailModel.name)}</h2>
                <span>{detailModel.description || detailModel.name}</span>
              </div>
              <button className="icon-btn" type="button" aria-label="Close model details" onClick={() => setDetailModelName(null)}>
                <Icon name="x" />
              </button>
            </div>

            <div className="model-modal-body">
              <div className="model-inspector-head">
                <div>
                  <span>Status</span>
                  <b>{detailModel.production_version ? "Production" : "Registered"}</b>
                </div>
                <div>
                  <span>Versions</span>
                  <b>{versionsLoading ? "Loading..." : detailVersions.length}</b>
                </div>
                <div>
                  <span>Updated</span>
                  <b>{formatRegistryTime(detailModel.last_updated_timestamp)}</b>
                </div>
                <div>
                  <span>Created</span>
                  <b>{formatRegistryTime(detailModel.creation_timestamp)}</b>
                </div>
              </div>

              <div className="model-section-title">Description</div>
              <div className="model-description-editor">
                <textarea
                  className="textarea"
                  value={descriptionDraft}
                  onChange={(event) => setDescriptionDraft(event.target.value)}
                  placeholder="Add a short business-facing description for this model."
                  maxLength={2000}
                />
                <div className="model-description-actions">
                  <span>{descriptionDraft.length}/2000</span>
                  <button
                    className="btn btn-primary"
                    type="button"
                    onClick={onSaveModelDescription}
                    disabled={descriptionSubmitting || descriptionDraft.trim() === (detailModel.description ?? "").trim()}
                  >
                    <Icon name={descriptionSubmitting ? "refresh" : "check"} className={descriptionSubmitting ? "spin" : undefined} />
                    <span>{descriptionSubmitting ? "Saving..." : "Save Description"}</span>
                  </button>
                </div>
              </div>

              <div className="model-section-title">Version control</div>
              <div className="model-version-control">
                <Field label="Version">
                  <select
                    className="input"
                    value={selectedRunId}
                    onChange={(event) => setSelectedRunId(event.target.value)}
                    disabled={!selectedModelName || versionsLoading || !versions.length}
                  >
                    {versionsLoading ? (
                      <option value="">Loading versions...</option>
                    ) : versions.length ? (
                      versions.map((version) => (
                        <option value={version.run_id} key={version.run_id}>
                          v{version.version} - {version.run_id.slice(0, 8)}
                        </option>
                      ))
                    ) : (
                      <option value="">No versions available</option>
                    )}
                  </select>
                </Field>
                <button className="btn btn-primary" type="button" onClick={onRollbackModel} disabled={rollbackSubmitting || versionsLoading || !selectedRunId}>
                  <Icon name={rollbackSubmitting ? "refresh" : "arrowUp"} className={rollbackSubmitting ? "spin" : undefined} />
                  <span>{rollbackSubmitting ? "Promoting..." : "Promote Version"}</span>
                </button>
                <button className="btn" type="button" onClick={onDemoteModel} disabled={demoteSubmitting || versionsLoading || !detailVersionIsProduction}>
                  <Icon name={demoteSubmitting ? "refresh" : "arrowDown"} className={demoteSubmitting ? "spin" : undefined} />
                  <span>{demoteSubmitting ? "Moving..." : "Move Out of Production"}</span>
                </button>
                <button
                  className="btn"
                  type="button"
                  onClick={onDownloadModel}
                  disabled={downloadSubmitting || versionsLoading || !selectedRunId}
                  title="Download model artifacts as a zip file"
                >
                  <Icon name={downloadSubmitting ? "refresh" : "download"} className={downloadSubmitting ? "spin" : undefined} />
                  <span>{downloadSubmitting ? "Downloading..." : "Download Model"}</span>
                </button>
              </div>
              {versionError && <div className="model-inline-error">{versionError}</div>}

              {detailVersion ? (
                <>
                  <div className="model-section-title">Selected version</div>
                  <div className="model-detail-grid">
                    <div>
                      <span>Version</span>
                      <b>v{detailVersion.version}</b>
                    </div>
                    <div>
                      <span>Stage</span>
                      <b>{detailVersion.current_stage || detailVersion.tags.stage || "Unassigned"}</b>
                    </div>
                    <div>
                      <span>Task</span>
                      <b>{detailVersion.model_task || detailVersion.tags.model_task || "Unknown"}</b>
                    </div>
                    <div>
                      <span>Run ID</span>
                      <b className="mono" title={detailVersion.run_id}>{detailVersion.run_id}</b>
                    </div>
                  </div>

                  <div className="model-section-title">Metrics</div>
                  {detailVersionMetricEntries.length ? (
                    <div className="model-kv-list">
                      {detailVersionMetricEntries.map(([key, value]) => (
                        <div key={key}>
                          <span>{key}</span>
                          <b>{formatMetric(value)}</b>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty compact">No metrics recorded for this version.</div>
                  )}

                  <div className="model-section-title">Tags</div>
                  {detailVersionTagEntries.length ? (
                    <div className="model-kv-list">
                      {detailVersionTagEntries.map(([key, value]) => (
                        <div key={key}>
                          <span>{key}</span>
                          <b>{value}</b>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty compact">No tags recorded for this version.</div>
                  )}

                  <div className="model-section-title">Training pipelines</div>
                  {detailVersionPipelineLogs.length ? (
                    <div className="model-pipeline-list">
                      {detailVersionPipelineLogs.map(({ version, log }) => (
                        <button
                          className="model-pipeline-row"
                          key={`${version.version}-${log.id}`}
                          type="button"
                          onClick={() => {
                            setDetailModelName(null);
                            setDetailLog(log);
                          }}
                        >
                          <span className={`status-dot ${pipelineStatusTone(log)}`} />
                          <div>
                            <b>v{version.version} - {log.model_task || log.type}</b>
                            <span>
                              {log.datasource_used || "Unknown datasource"}
                              {log.mlflow_run_id ? ` · ${log.mlflow_run_id.slice(0, 8)}` : ""}
                            </span>
                          </div>
                          <span className={`model-pipeline-status ${log.status === "Success" ? "is-success" : log.status === "Failed" ? "is-failed" : "is-running"}`}>
                            {pipelineStatusLabel(log)}
                          </span>
                          <small>{log.timestamp ? new Date(log.timestamp).toLocaleString() : "Unknown time"}</small>
                        </button>
                      ))}
                    </div>
                  ) : logsLoading ? (
                    <div className="empty compact">Loading pipeline history...</div>
                  ) : (
                    <div className="empty compact">No pipeline history found for this model's versions.</div>
                  )}
                </>
              ) : versionsLoading || detailModelName !== selectedModelName ? (
                <div className="empty">Loading version information...</div>
              ) : (
                <div className="empty">No version information available for this model.</div>
              )}
            </div>
          </div>
        </>
      )}
    </main>
  );
}
