"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/common/icons";
import { Card, Field, Select } from "@/components/common/primitives";
import {
  getLocationOptions,
  getMetricOptions,
  getModelVersions,
  getPipelineLogs,
  getRegisteredModels,
  rollbackModel,
  trainModel,
  validateTrainingRequest,
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

const DATA_SOURCE_OPTIONS: Array<{ value: TrainingDataSource; label: string }> = [
  { value: "csv", label: "Cleaned CSV" },
  { value: "db", label: "Database" },
];

const DEFAULT_SITE = "Panther_parking_Lorriane";
const DEFAULT_METRICS = ["electricity"];

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
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [logs, setLogs] = useState<PipelineLog[]>([]);
  const [locationOptions, setLocationOptions] = useState<LocationOption[]>([]);
  const [metricOptions, setMetricOptions] = useState<MetricOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modelTask, setModelTask] = useState<ModelTask>("forecasting");
  const [dataSource, setDataSource] = useState<TrainingDataSource>("csv");
  const [locationId, setLocationId] = useState(DEFAULT_SITE);
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>(DEFAULT_METRICS);
  const [locationQuery, setLocationQuery] = useState(DEFAULT_SITE);
  const [metricQuery, setMetricQuery] = useState("");
  const [startDate, setStartDate] = useState(defaultStartDate);
  const [endDate, setEndDate] = useState(defaultEndDate);
  const [submitting, setSubmitting] = useState(false);
  const [rollbackSubmitting, setRollbackSubmitting] = useState(false);
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
  const [detailModelName, setDetailModelName] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      setLoading(true);
      setError(null);

      try {
        const [modelData, logData] = await Promise.all([
          getRegisteredModels(controller.signal),
          getPipelineLogs(controller.signal),
        ]);
        setModels(modelData.models);
        setLogs(logData.logs);
        setSelectedModelName((current) => current || modelData.models[0]?.name || "");

        const [locationData, metricData] = await Promise.all([
          getLocationOptions({ limit: 8 }, controller.signal),
          getMetricOptions(controller.signal),
        ]);
        setLocationOptions(locationData.locations);
        setMetricOptions(metricData.metrics);
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : "Unable to load AI engineering data.");
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    async function queryLocations() {
      try {
        const data = await getLocationOptions({ q: locationQuery, limit: 8 }, controller.signal);
        setLocationOptions(data.locations);
      } catch {
        if (!controller.signal.aborted) setLocationOptions([]);
      }
    }

    void queryLocations();
    return () => controller.abort();
  }, [locationQuery]);

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

  async function refreshLogs() {
    const logData = await getPipelineLogs();
    setLogs(logData.logs);
  }

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
  const detailModel = models.find((model) => model.name === detailModelName) ?? null;
  const selectedVersion = versions.find((version) => version.run_id === selectedRunId) ?? null;
  const detailVersion = detailModelName === selectedModelName ? selectedVersion : null;
  const detailVersions = detailModelName === selectedModelName ? versions : [];
  const detailVersionMetricEntries = Object.entries(detailVersion?.metrics ?? {}).sort(([left], [right]) => left.localeCompare(right));
  const detailVersionTagEntries = Object.entries(detailVersion?.tags ?? {}).sort(([left], [right]) => left.localeCompare(right));
  const selectedMetricsKey = selectedMetrics.join(",");
  const validationInputReady = Boolean(locationId.trim() && selectedMetrics.length && startDate && endDate);
  const trainingPayload = useMemo<TrainModelPayload>(
    () => ({
      site_id: locationId.trim(),
      metrics: selectedMetrics,
      time_range_start: isoFromDateInput(startDate),
      time_range_end: isoFromDateInput(endDate, true),
      model_task: modelTask,
      data_source: dataSource,
    }),
    [dataSource, endDate, locationId, modelTask, selectedMetrics, startDate],
  );
  const canTrain = validationInputReady && !submitting && !validationLoading && trainingValidation?.valid !== false;

  useEffect(() => {
    if (!validationInputReady) return;

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
  }, [selectedMetricsKey, trainingPayload, validationInputReady]);

  function chooseLocation(location: LocationOption) {
    setLocationId(location.id);
    setLocationQuery(location.id);
    setLocationPickerOpen(false);
  }

  function toggleMetric(metricId: string) {
    setSelectedMetrics((current) => (current.includes(metricId) ? current.filter((metric) => metric !== metricId) : [...current, metricId]));
  }

  function openModelDetails(modelName: string) {
    setSelectedModelName(modelName);
    setDetailModelName(modelName);
  }

  async function onTrainModel() {
    const resolvedLocationId = locationId.trim();
    const knownMetricIds = new Set(metricOptions.map((metric) => metric.id));
    const invalidMetrics = selectedMetrics.filter((metric) => !knownMetricIds.has(metric));

    if (!resolvedLocationId) {
      setError("Select a site/building from the list before training.");
      return;
    }

    if (!selectedMetrics.length) {
      setError("At least one metric is required.");
      return;
    }

    if (invalidMetrics.length) {
      setError(`Unknown metric(s): ${invalidMetrics.join(", ")}`);
      return;
    }

    setSubmitting(true);
    setError(null);
    setTrainMessage(null);

    try {
      const validation = await validateTrainingRequest(trainingPayload);
      setTrainingValidation(validation);

      if (!validation.valid) {
        setError("Training data is not valid. Review the validation details below.");
        return;
      }

      const response = await trainModel(trainingPayload);
      setTrainMessage(`${response.message} Task ${response.task_id} queued.`);
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

  return (
    <main className="page models-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">AI Engineering</h1>
          <p className="page-sub">Registered models, production status, and recent pipeline activity.</p>
        </div>
      </div>

      {error && <div className="anomaly-error">{error}</div>}
      {trainMessage && <div className="models-success">{trainMessage}</div>}

      <div className="grid models-grid">
        <Card
          title="Train Model"
          sub="Queue a new ML pipeline run"
          icon="spark2"
          actions={
            <button className="btn btn-primary" type="button" onClick={onTrainModel} disabled={!canTrain}>
              <Icon name={submitting ? "refresh" : "plus"} className={submitting ? "spin" : undefined} />
              <span>{submitting ? "Queueing..." : "Train"}</span>
            </button>
          }
        >
          <div className="train-model-form">
            <Field label="Task">
              <Select value={modelTask} onChange={setModelTask} options={MODEL_TASK_OPTIONS} />
            </Field>
            <Field label="Data source">
              <Select value={dataSource} onChange={setDataSource} options={DATA_SOURCE_OPTIONS} />
            </Field>
            <Field label="Site / building">
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
                />
                {locationPickerOpen && locationQuery && locationOptions.length > 0 && (
                  <div className="model-picker-list">
                    {locationOptions.map((location) => (
                      <button key={location.id} type="button" onClick={() => chooseLocation(location)}>
                        <b title={location.id}>{location.id}</b>
                        <span title={location.name}>{location.name}</span>
                      </button>
                    ))}
                  </div>
                )}
                {locationPickerOpen && locationQuery && locationOptions.length === 0 && (
                  <div className="model-picker-empty">No matches found.</div>
                )}
              </div>
            </Field>
            <Field label="Metrics">
              <input className="input" value={metricQuery} onChange={(event) => setMetricQuery(event.target.value)} />
              <div className="metric-choice-list">
                {filteredMetrics.map((metric) => (
                  <button key={metric.id} type="button" className={selectedMetrics.includes(metric.id) ? "is-selected" : ""} onClick={() => toggleMetric(metric.id)}>
                    {metric.id}
                  </button>
                ))}
              </div>
              <div className="metric-chip-list">
                {selectedMetrics.map((metric) => (
                  <button key={metric} type="button" onClick={() => toggleMetric(metric)}>
                    {metric}
                    <Icon name="x" />
                  </button>
                ))}
              </div>
            </Field>
            <Field label="Start date">
              <input className="input" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
            </Field>
            <Field label="End date">
              <input className="input" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
            </Field>
          </div>
          <TrainingValidationPanel
            dataSource={dataSource}
            validation={validationInputReady ? trainingValidation : null}
            loading={validationInputReady && validationLoading}
            error={validationInputReady ? validationError : null}
          />
        </Card>

        <Card
          title="Rollback Model"
          sub={versionsLoading ? "Querying versions..." : "Promote a registered version"}
          icon="refresh"
          actions={
            <button className="btn" type="button" onClick={onRollbackModel} disabled={rollbackSubmitting || versionsLoading || !selectedRunId}>
              <Icon name={rollbackSubmitting ? "refresh" : "arrowUp"} className={rollbackSubmitting ? "spin" : undefined} />
              <span>{rollbackSubmitting ? "Promoting..." : "Promote"}</span>
            </button>
          }
        >
          <div className="rollback-form">
            <Field label="Model">
              <select className="input" value={selectedModelName} onChange={(event) => setSelectedModelName(event.target.value)} disabled={loading || !models.length}>
                {!models.length && <option value="">No models available</option>}
                {models.map((model) => (
                  <option value={model.name} key={model.name}>
                    {model.name}
                  </option>
                ))}
              </select>
            </Field>
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
                      {version.current_stage ? ` - ${version.current_stage}` : ""}
                    </option>
                  ))
                ) : (
                  <option value="">No versions available</option>
                )}
              </select>
            </Field>
          </div>
          {versionError && <div className="model-inline-error">{versionError}</div>}
        </Card>

        <Card title="Registered Models" sub={loading ? "Loading registry..." : `${models.length} models`} icon="cpu">
          {loading ? (
            <div className="empty">Loading models...</div>
          ) : models.length ? (
            <div className="model-list">
              {models.map((model) => (
                <button
                  className={`model-row ${selectedModelName === model.name ? "is-selected" : ""}`}
                  key={model.name}
                  type="button"
                  onClick={() => openModelDetails(model.name)}
                >
                  <div>
                    <b>{model.name}</b>
                    <span>{model.description || "No description"}</span>
                  </div>
                  <div className="model-version-stack">
                    <span className="badge badge-neutral">Registered</span>
                    {model.latest_versions.length ? (
                      model.latest_versions.map((version) => (
                        <span className="badge badge-neutral" key={`${model.name}-${version.version}`}>
                          v{version.version}
                          {version.current_stage ? ` . ${version.current_stage}` : ""}
                        </span>
                      ))
                    ) : (
                      <span className="badge badge-neutral">No versions</span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="empty">No registered models found.</div>
          )}
        </Card>

        <Card title="Pipeline Activity" sub={loading ? "Loading logs..." : `${logs.length} recent runs`} icon="table">
          {loading ? (
            <div className="empty">Loading pipeline logs...</div>
          ) : logs.length ? (
            <div className="model-log-list">
              {logs.map((log) => (
                <div className="model-log-row" key={log.id}>
                  <span className={`status-dot ${log.status === "Success" ? "s-green" : log.status === "Failed" ? "s-red" : "s-yellow"}`} />
                  <div>
                    <b>{log.model_task || log.type}</b>
                    <span className="model-log-source" title={log.datasource_used || "Unknown datasource"}>
                      {log.datasource_used || "Unknown datasource"}
                    </span>
                  </div>
                  <span className="badge badge-neutral">{log.status}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty">No pipeline logs found.</div>
          )}
        </Card>
      </div>

      <div className="card models-note">
        <Icon name="shield" />
        <span>Visible to Admin and AI Engineer roles.</span>
      </div>

      {detailModel && (
        <>
          <div className="overlay" onClick={() => setDetailModelName(null)} />
          <div className="model-modal" role="dialog" aria-label={`${detailModel.name} details`}>
            <div className="model-modal-head">
              <div>
                <h2>{detailModel.name}</h2>
                <span>{detailModel.description || "No description"}</span>
              </div>
              <button className="icon-btn" type="button" aria-label="Close model details" onClick={() => setDetailModelName(null)}>
                <Icon name="x" />
              </button>
            </div>

            <div className="model-modal-body">
              <div className="model-inspector-head">
                <div>
                  <span>Status</span>
                  <b>Registered</b>
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
