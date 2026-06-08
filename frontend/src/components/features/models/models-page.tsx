"use client";

import { useEffect, useRef, useState } from "react";
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
  type LocationOption,
  type MetricOption,
  type ModelTask,
  type ModelVersion,
  type PipelineLog,
  type RegisteredModel,
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
  const [trainMessage, setTrainMessage] = useState<string | null>(null);
  const [locationPickerOpen, setLocationPickerOpen] = useState(false);

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
        return;
      }

      try {
        const data = await getModelVersions(selectedModelName, controller.signal);
        setVersions(data.versions);
        setSelectedRunId(data.versions[0]?.run_id || "");
      } catch {
        setVersions([]);
        setSelectedRunId("");
      }
    }

    void loadVersions();
    return () => controller.abort();
  }, [selectedModelName]);

  const filteredMetrics = metricOptions
    .filter((metric) => `${metric.id} ${metric.description ?? ""}`.toLowerCase().includes(metricQuery.toLowerCase()))
    .slice(0, 8);

  function chooseLocation(location: LocationOption) {
    setLocationId(location.id);
    setLocationQuery(location.id);
    setLocationPickerOpen(false);
  }

  function toggleMetric(metricId: string) {
    setSelectedMetrics((current) => (current.includes(metricId) ? current.filter((metric) => metric !== metricId) : [...current, metricId]));
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
      const response = await trainModel({
        site_id: resolvedLocationId,
        metrics: selectedMetrics,
        time_range_start: isoFromDateInput(startDate),
        time_range_end: isoFromDateInput(endDate, true),
        model_task: modelTask,
        data_source: dataSource,
      });
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
            <button className="btn btn-primary" type="button" onClick={onTrainModel} disabled={submitting}>
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
        </Card>

        <Card
          title="Rollback Model"
          sub="Promote a registered version"
          icon="refresh"
          actions={
            <button className="btn" type="button" onClick={onRollbackModel} disabled={rollbackSubmitting || !selectedRunId}>
              <Icon name={rollbackSubmitting ? "refresh" : "arrowUp"} className={rollbackSubmitting ? "spin" : undefined} />
              <span>{rollbackSubmitting ? "Promoting..." : "Promote"}</span>
            </button>
          }
        >
          <div className="rollback-form">
            <Field label="Model">
              <Select value={selectedModelName} onChange={setSelectedModelName} options={models.map((model) => ({ value: model.name, label: model.name }))} />
            </Field>
            <Field label="Version">
              <Select
                value={selectedRunId}
                onChange={setSelectedRunId}
                options={versions.map((version) => ({
                  value: version.run_id,
                  label: `v${version.version} . ${version.run_id.slice(0, 8)}`,
                }))}
              />
            </Field>
          </div>
        </Card>

        <Card title="Registered Models" sub={loading ? "Loading registry..." : `${models.length} models`} icon="cpu">
          {loading ? (
            <div className="empty">Loading models...</div>
          ) : models.length ? (
            <div className="model-list">
              {models.map((model) => (
                <div className="model-row" key={model.name}>
                  <div>
                    <b>{model.name}</b>
                    <span>{model.description || "No description"}</span>
                  </div>
                  <div className="model-version-stack">
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
                </div>
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
    </main>
  );
}
