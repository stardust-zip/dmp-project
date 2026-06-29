"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/common/icons";
import { Card, Field, Select } from "@/components/common/primitives";
import { ModelDetailModal } from "@/components/features/models/model-detail-modal";
import { displayLocationName, displayModelName, humanizeIdentifier } from "@/lib/format";
import {
  backfillAnomalyInference,
  cancelPipelineLog,
  getLocationOptions,
  getMetricOptions,
  getPipelineLogs,
  getRegisteredModels,
  trainModel,
  validateTrainingRequest,
  type AnomalyBackfillPayload,
  type LocationOption,
  type MetricOption,
  type ModelTask,
  type PipelineLog,
  type RegisteredModel,
  type TrainModelPayload,
  type TrainingValidationResponse,
  type TrainingDataSource,
  type WeatherMode,
} from "@/lib/models-api";

const MODEL_TASK_OPTIONS: Array<{ value: ModelTask; label: string }> = [
  { value: "forecasting", label: "Forecasting" },
  { value: "anomaly_detection", label: "Anomaly Detection" },
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

const MIN_TRAINING_DAYS = 30;

// The training dataset only runs through 2017-09-30; never allow a later end date.
const TRAINING_DATA_END_DATE = "2017-09-30";

function defaultStartDate() {
  // 2017-07-01 — a ~3-month window ending at the dataset cap.
  return "2017-07-01";
}

function defaultEndDate() {
  return TRAINING_DATA_END_DATE;
}

function clampEndDate(value: string) {
  return value && value > TRAINING_DATA_END_DATE ? TRAINING_DATA_END_DATE : value;
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
  const terminalLogRef = useRef<HTMLPreElement | null>(null);
  const registryRefreshRunIdsRef = useRef<Set<string>>(new Set());
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [logs, setLogs] = useState<PipelineLog[]>([]);
  const [metricOptions, setMetricOptions] = useState<MetricOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [logsLoading, setLogsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modelTask, setModelTask] = useState<ModelTask>("forecasting");
  const [dataSource, setDataSource] = useState<TrainingDataSource>("csv");
  const [forecastHorizon, setForecastHorizon] = useState(24);
  const [weatherMode, setWeatherMode] = useState<WeatherMode>("none");
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>([]);
  const [metricQuery, setMetricQuery] = useState("");
  const [startDate, setStartDate] = useState(defaultStartDate);
  const [endDate, setEndDate] = useState(defaultEndDate);
  const [submitting, setSubmitting] = useState(false);
  const [selectedModelName, setSelectedModelName] = useState("");
  const [trainingValidation, setTrainingValidation] = useState<TrainingValidationResponse | null>(null);
  const [validationLoading, setValidationLoading] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [trainMessage, setTrainMessage] = useState<string | null>(null);
  const [detailModelName, setDetailModelName] = useState<string | null>(null);
  const [trainModalOpen, setTrainModalOpen] = useState(false);
  const [pipelineModalOpen, setPipelineModalOpen] = useState(false);
  const [detailLog, setDetailLog] = useState<PipelineLog | null>(null);
  const [cancelSubmitting, setCancelSubmitting] = useState(false);
  const [modelQuery, setModelQuery] = useState("");
  const [modelTaskFilter, setModelTaskFilter] = useState<"all" | ModelTask | "unknown">("all");
  const [modelStageFilter, setModelStageFilter] = useState<"all" | "production" | "non_production">("all");
  const [modelMetricFilter, setModelMetricFilter] = useState("all");
  const [backfillModalOpen, setBackfillModalOpen] = useState(false);
  const [backfillStartDate, setBackfillStartDate] = useState("2017-10-01");
  const [backfillEndDate, setBackfillEndDate] = useState("2017-12-31");
  const [backfillSubmitting, setBackfillSubmitting] = useState(false);
  const [trainingMode, setTrainingMode] = useState<"all" | "single">("all");
  const [selectedBuildingId, setSelectedBuildingId] = useState<string | null>(null);
  const [buildingOptions, setBuildingOptions] = useState<LocationOption[]>([]);
  const [buildingQuery, setBuildingQuery] = useState("");
  const [buildingsLoading, setBuildingsLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      setLoading(true);
      setError(null);

      try {
        const [modelData, logData, metricData] = await Promise.all([
          getRegisteredModels(controller.signal),
          getPipelineLogs(controller.signal),
          getMetricOptions(controller.signal),
        ]);
        setModels(modelData.models);
        setLogs(logData.logs);
        registryRefreshRunIdsRef.current = new Set(
          logData.logs.filter(isSuccessfulPipelineLog).map((log) => log.mlflow_run_id as string),
        );
        setSelectedModelName((current) => current || modelData.models[0]?.name || "");
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

      return modelData.models;
    },
    [],
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

  // Load building options when training modal opens in single-building mode
  useEffect(() => {
    if (!trainModalOpen || trainingMode !== "single") return;

    const controller = new AbortController();
    setBuildingsLoading(true);
    getLocationOptions({ limit: 200 }, controller.signal)
      .then((data) => setBuildingOptions(data.locations))
      .catch(() => { })
      .finally(() => {
        if (!controller.signal.aborted) setBuildingsLoading(false);
      });

    return () => controller.abort();
  }, [trainModalOpen, trainingMode]);

  // Reset building selection when switching to "all buildings" mode
  useEffect(() => {
    if (trainingMode === "all") {
      setSelectedBuildingId(null);
      setBuildingQuery("");
    }
  }, [trainingMode]);

  const filteredMetrics = metricOptions
    .filter((metric) => `${metric.id} ${metric.description ?? ""}`.toLowerCase().includes(metricQuery.toLowerCase()))
    .slice(0, 8);
  const filteredBuildings = useMemo(() => {
    const query = buildingQuery.trim().toLowerCase();
    if (!query) return buildingOptions.slice(0, 50);
    return buildingOptions
      .filter(
        (loc) =>
          loc.id.toLowerCase().includes(query) ||
          loc.name.toLowerCase().includes(query),
      )
      .slice(0, 50);
  }, [buildingOptions, buildingQuery]);
  const buildingSelectOptions = useMemo(
    () =>
      buildingOptions
        .filter((loc) => loc.parent_id != null) // buildings only, not sites
        .map((loc) => ({
          value: loc.id,
          label: displayLocationName(loc.name, loc.id),
        })),
    [buildingOptions],
  );

  const metricSelectOptions = useMemo(
    () =>
      metricOptions.map((metric) => ({
        value: metric.id,
        label: humanizeIdentifier(metric.id),
      })),
    [metricOptions],
  );

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
  const detailTerminalLog = detailLog ? pipelineTerminalLog(detailLog) : "";
  const selectedMetricsKey = selectedMetrics.join(",");
  const selectedTaskLabel = MODEL_TASK_OPTIONS.find((option) => option.value === modelTask)?.label ?? modelTask;
  const trainingTaskImplemented =
    modelTask === "anomaly_detection" || modelTask === "forecasting";
  const metricSelectionValid =
    modelTask === "forecasting" ? selectedMetrics.length === 1 : true;
  const isAnomalyDetection = modelTask === "anomaly_detection";
  const isForecasting = modelTask === "forecasting";
  const validationInputReady = isAnomalyDetection
    ? Boolean(startDate && endDate)
    : Boolean(selectedMetrics.length && startDate && endDate);
  const dateRangeDays = startDate && endDate
    ? Math.round((new Date(endDate).getTime() - new Date(startDate).getTime()) / 86_400_000)
    : 0;
  const dateRangeValid = dateRangeDays >= MIN_TRAINING_DAYS;
  const trainingPayload = useMemo<TrainModelPayload>(
    () => ({
      site_id: null,
      building_id: isForecasting ? null : trainingMode === "single" ? selectedBuildingId : null,
      metrics: isAnomalyDetection ? ["electricity"] : selectedMetrics,
      time_range_start: isoFromDateInput(startDate),
      time_range_end: isoFromDateInput(endDate, true),
      model_task: modelTask,
      data_source: dataSource,
      ...(isForecasting
        ? { algorithm: "xgboost", forecast_horizon_hours: forecastHorizon, weather_mode: weatherMode }
        : {}),
    }),
    [
      dataSource,
      endDate,
      forecastHorizon,
      isAnomalyDetection,
      isForecasting,
      modelTask,
      selectedBuildingId,
      selectedMetrics,
      startDate,
      trainingMode,
      weatherMode,
    ],
  );
  const buildingSelectionValid = trainingMode === "all" || Boolean(selectedBuildingId);
  const canTrain = trainingTaskImplemented && metricSelectionValid && validationInputReady && dateRangeValid && buildingSelectionValid && !submitting && !validationLoading && trainingValidation?.valid !== false;

  useEffect(() => {
    if (!terminalLogRef.current) return;
    terminalLogRef.current.scrollTop = terminalLogRef.current.scrollHeight;
  }, [detailTerminalLog]);

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

  function toggleMetric(metricId: string) {
    setSelectedMetrics((current) => (current.includes(metricId) ? current.filter((metric) => metric !== metricId) : [...current, metricId]));
  }

  function openModelDetails(modelName: string) {
    setSelectedModelName(modelName);
    setDetailModelName(modelName);
  }

  async function onTrainModel() {
    if (!trainingTaskImplemented) {
      setError(`${selectedTaskLabel} training pipeline is not implemented yet.`);
      return;
    }

    if (!isAnomalyDetection) {
      const knownMetricIds = new Set(metricOptions.map((metric) => metric.id));
      const invalidMetrics = selectedMetrics.filter((metric) => !knownMetricIds.has(metric));

      if (!selectedMetrics.length) {
        setError("At least one metric is required.");
        return;
      }

      if (!metricSelectionValid) {
        setError(`${selectedTaskLabel} training requires exactly one metric per model.`);
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
                {!isAnomalyDetection && !isForecasting && (
                  <Field label="Training scope">
                    <div className="training-mode-toggle">
                      <button
                        type="button"
                        className={trainingMode === "all" ? "is-active" : ""}
                        onClick={() => setTrainingMode("all")}
                      >
                        All Buildings
                      </button>
                      <button
                        type="button"
                        className={trainingMode === "single" ? "is-active" : ""}
                        onClick={() => setTrainingMode("single")}
                      >
                        Single Building
                      </button>
                    </div>
                  </Field>
                )}
                {!isAnomalyDetection && !isForecasting && trainingMode === "single" && (
                  <Field label="Building">
                    <Select
                      value={selectedBuildingId ?? ""}
                      onChange={setSelectedBuildingId}
                      options={buildingSelectOptions}
                      searchable
                      searchPlaceholder="Search by ID or name..."
                    />
                  </Field>
                )}
                {!isAnomalyDetection && (
                  <Field label="Metric">
                    <Select
                      value={selectedMetrics[0] ?? ""}
                      onChange={(metric) => setSelectedMetrics(metric ? [metric] : [])}
                      options={metricSelectOptions}
                      searchable
                      searchPlaceholder="Search metrics..."
                    />
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
                        <input type="date" max={TRAINING_DATA_END_DATE} value={endDate} onChange={(event) => setEndDate(clampEndDate(event.target.value))} />
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
                )}
                {isForecasting && (
                  <Field label="Weather features">
                    <div className="training-mode-toggle">
                      <button
                        type="button"
                        className={weatherMode === "none" ? "is-active" : ""}
                        onClick={() => setWeatherMode("none")}
                        title="Energy-only features (no weather)"
                      >
                        None
                      </button>
                      <button
                        type="button"
                        className={weatherMode === "forecast" ? "is-active" : ""}
                        onClick={() => setWeatherMode("forecast")}
                        title="Include weather aligned to the target time"
                      >
                        Forecast
                      </button>
                    </div>
                  </Field>
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
        <ModelDetailModal
          model={detailModel}
          onClose={() => setDetailModelName(null)}
          onModelsChanged={setModels}
          onMessage={setTrainMessage}
          onError={setError}
          onOpenPipelineLog={setDetailLog}
        />
      )}
    </main>
  );
}
