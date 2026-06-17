"use client";

import { useEffect, useMemo, useState } from "react";
import { Icon } from "@/components/common/icons";
import { Field } from "@/components/common/primitives";
import { displayModelName } from "@/lib/format";
import {
  demoteModel,
  downloadModelFile,
  getModelVersions,
  getPipelineLogs,
  getRegisteredModels,
  rollbackModel,
  updateModelDescription,
  type ModelVersion,
  type PipelineLog,
  type RegisteredModel,
} from "@/lib/models-api";

interface ModelDetailModalProps {
  model: RegisteredModel;
  onClose: () => void;
  onModelsChanged?: (models: RegisteredModel[]) => void;
  onMessage?: (message: string) => void;
  onError?: (message: string) => void;
  onOpenPipelineLog?: (log: PipelineLog) => void;
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

export function ModelDetailModal({
  model,
  onClose,
  onModelsChanged,
  onMessage,
  onError,
  onOpenPipelineLog,
}: ModelDetailModalProps) {
  const [versions, setVersions] = useState<ModelVersion[]>([]);
  const [logs, setLogs] = useState<PipelineLog[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [logsLoading, setLogsLoading] = useState(false);
  const [versionError, setVersionError] = useState<string | null>(null);
  const [descriptionDraft, setDescriptionDraft] = useState(model.description ?? "");
  const [descriptionSubmitting, setDescriptionSubmitting] = useState(false);
  const [rollbackSubmitting, setRollbackSubmitting] = useState(false);
  const [demoteSubmitting, setDemoteSubmitting] = useState(false);
  const [downloadSubmitting, setDownloadSubmitting] = useState(false);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  useEffect(() => {
    const controller = new AbortController();

    async function loadVersions() {
      setVersionsLoading(true);
      setVersionError(null);
      try {
        const data = await getModelVersions(model.name, controller.signal);
        setVersions(data.versions);
        setSelectedRunId((current) => (data.versions.some((version) => version.run_id === current) ? current : data.versions[0]?.run_id || ""));
      } catch (err) {
        if (!controller.signal.aborted) {
          setVersions([]);
          setSelectedRunId("");
          setVersionError(err instanceof Error ? err.message : "Unable to load model versions.");
        }
      } finally {
        if (!controller.signal.aborted) setVersionsLoading(false);
      }
    }

    void loadVersions();
    return () => controller.abort();
  }, [model.name]);

  useEffect(() => {
    const controller = new AbortController();

    async function loadLogs() {
      setLogsLoading(true);
      try {
        const data = await getPipelineLogs(controller.signal);
        setLogs(data.logs);
      } catch {
        if (!controller.signal.aborted) setLogs([]);
      } finally {
        if (!controller.signal.aborted) setLogsLoading(false);
      }
    }

    void loadLogs();
    return () => controller.abort();
  }, []);

  const selectedVersion = versions.find((version) => version.run_id === selectedRunId) ?? null;
  const selectedVersionIsProduction = Boolean(model.production_version?.run_id && selectedVersion?.run_id && model.production_version.run_id === selectedVersion.run_id);
  const metricEntries = Object.entries(selectedVersion?.metrics ?? {}).sort(([left], [right]) => left.localeCompare(right));
  const tagEntries = Object.entries(selectedVersion?.tags ?? {}).sort(([left], [right]) => left.localeCompare(right));
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
  const versionPipelineLogs = versions.flatMap((version) =>
    (pipelineLogsByRunId.get(version.run_id) ?? []).map((log) => ({ version, log })),
  );

  async function refreshModels() {
    const modelData = await getRegisteredModels();
    onModelsChanged?.(modelData.models);
    return modelData.models;
  }

  async function onSaveModelDescription() {
    setDescriptionSubmitting(true);
    onError?.("");
    try {
      const response = await updateModelDescription(model.name, { description: descriptionDraft });
      const models = await refreshModels();
      onModelsChanged?.(models.map((item) => (item.name === response.name ? { ...item, description: response.description } : item)));
      setDescriptionDraft(response.description);
      onMessage?.(`${displayModelName(model.name)} description updated.`);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Unable to update model description.");
    } finally {
      setDescriptionSubmitting(false);
    }
  }

  async function onPromoteModel() {
    if (!selectedRunId) {
      onError?.("Select a model version before promoting.");
      return;
    }

    setRollbackSubmitting(true);
    try {
      const response = await rollbackModel({ model_name: model.name, mlflow_run_id: selectedRunId });
      onMessage?.(`${response.model_name} v${response.version} promoted to production.`);
      await refreshModels();
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Unable to promote model.");
    } finally {
      setRollbackSubmitting(false);
    }
  }

  async function onDemoteModel() {
    if (!selectedRunId) {
      onError?.("Select a production model version before removing it from production.");
      return;
    }

    setDemoteSubmitting(true);
    try {
      const response = await demoteModel({ model_name: model.name, mlflow_run_id: selectedRunId });
      onMessage?.(`${response.model_name} v${response.version} moved out of production.`);
      await refreshModels();
      const versionData = await getModelVersions(model.name);
      setVersions(versionData.versions);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Unable to move model out of production.");
    } finally {
      setDemoteSubmitting(false);
    }
  }

  function onDownloadModel() {
    if (!selectedRunId) {
      onError?.("Select a model version before downloading.");
      return;
    }

    const version = versions.find((item) => item.run_id === selectedRunId);
    if (!version) {
      onError?.("Selected version not found in registry.");
      return;
    }

    setDownloadSubmitting(true);
    downloadModelFile(model.name, version.version)
      .then(({ blob, filename }) => {
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        URL.revokeObjectURL(url);
        onMessage?.(`${filename} downloaded.`);
      })
      .catch((err: unknown) => {
        onError?.(err instanceof Error ? err.message : "Unable to download model.");
      })
      .finally(() => setDownloadSubmitting(false));
  }

  return (
    <>
      <button className="overlay" type="button" aria-label="Close model details" onClick={onClose} />
      <div className="model-modal" role="dialog" aria-label={`${model.name} details`}>
        <div className="model-modal-head">
          <div>
            <h2 title={model.name}>{displayModelName(model.name)}</h2>
            <span>{model.description || model.name}</span>
          </div>
          <button className="icon-btn" type="button" aria-label="Close model details" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>

        <div className="model-modal-body">
          <div className="model-inspector-head">
            <div>
              <span>Status</span>
              <b>{model.production_version ? "Production" : "Registered"}</b>
            </div>
            <div>
              <span>Versions</span>
              <b>{versionsLoading ? "Loading..." : versions.length}</b>
            </div>
            <div>
              <span>Updated</span>
              <b>{formatRegistryTime(model.last_updated_timestamp)}</b>
            </div>
            <div>
              <span>Created</span>
              <b>{formatRegistryTime(model.creation_timestamp)}</b>
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
              <button className="btn btn-primary" type="button" onClick={onSaveModelDescription} disabled={descriptionSubmitting || descriptionDraft.trim() === (model.description ?? "").trim()}>
                <Icon name={descriptionSubmitting ? "refresh" : "check"} className={descriptionSubmitting ? "spin" : undefined} />
                <span>{descriptionSubmitting ? "Saving..." : "Save Description"}</span>
              </button>
            </div>
          </div>

          <div className="model-section-title">Version control</div>
          <div className="model-version-control">
            <Field label="Version">
              <select className="input" value={selectedRunId} onChange={(event) => setSelectedRunId(event.target.value)} disabled={versionsLoading || !versions.length}>
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
            <button className="btn btn-primary" type="button" onClick={onPromoteModel} disabled={rollbackSubmitting || versionsLoading || !selectedRunId}>
              <Icon name={rollbackSubmitting ? "refresh" : "arrowUp"} className={rollbackSubmitting ? "spin" : undefined} />
              <span>{rollbackSubmitting ? "Promoting..." : "Promote Version"}</span>
            </button>
            <button className="btn" type="button" onClick={onDemoteModel} disabled={demoteSubmitting || versionsLoading || !selectedVersionIsProduction}>
              <Icon name={demoteSubmitting ? "refresh" : "arrowDown"} className={demoteSubmitting ? "spin" : undefined} />
              <span>{demoteSubmitting ? "Moving..." : "Move Out of Production"}</span>
            </button>
            <button className="btn" type="button" onClick={onDownloadModel} disabled={downloadSubmitting || versionsLoading || !selectedRunId} title="Download model artifacts as a zip file">
              <Icon name={downloadSubmitting ? "refresh" : "download"} className={downloadSubmitting ? "spin" : undefined} />
              <span>{downloadSubmitting ? "Downloading..." : "Download Model"}</span>
            </button>
          </div>
          {versionError && <div className="model-inline-error">{versionError}</div>}

          {selectedVersion ? (
            <>
              <div className="model-section-title">Selected version</div>
              <div className="model-detail-grid">
                <div>
                  <span>Version</span>
                  <b>v{selectedVersion.version}</b>
                </div>
                <div>
                  <span>Stage</span>
                  <b>{selectedVersion.current_stage || selectedVersion.tags.stage || "Unassigned"}</b>
                </div>
                <div>
                  <span>Task</span>
                  <b>{selectedVersion.model_task || selectedVersion.tags.model_task || "Unknown"}</b>
                </div>
                <div>
                  <span>Run ID</span>
                  <b className="mono" title={selectedVersion.run_id}>{selectedVersion.run_id}</b>
                </div>
              </div>

              <div className="model-section-title">Metrics</div>
              {metricEntries.length ? (
                <div className="model-kv-list">
                  {metricEntries.map(([key, value]) => (
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
              {tagEntries.length ? (
                <div className="model-kv-list">
                  {tagEntries.map(([key, value]) => (
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
              {versionPipelineLogs.length ? (
                <div className="model-pipeline-list">
                  {versionPipelineLogs.map(({ version, log }) => (
                    <button
                      className="model-pipeline-row"
                      key={`${version.version}-${log.id}`}
                      type="button"
                      onClick={() => {
                        if (onOpenPipelineLog) {
                          onClose();
                          onOpenPipelineLog(log);
                        }
                      }}
                    >
                      <span className={`status-dot ${pipelineStatusTone(log)}`} />
                      <div>
                        <b>v{version.version} - {log.model_task || log.type}</b>
                        <span>
                          {log.datasource_used || "Unknown datasource"}
                          {log.mlflow_run_id ? ` - ${log.mlflow_run_id.slice(0, 8)}` : ""}
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
          ) : versionsLoading ? (
            <div className="empty">Loading version information...</div>
          ) : (
            <div className="empty">No version information available for this model.</div>
          )}
        </div>
      </div>
    </>
  );
}
