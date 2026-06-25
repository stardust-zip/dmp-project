"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  compareVersions,
  getDriftTimeline,
  getMonitoringAlerts,
  getMonitoringSummary,
  getPerformanceTimeline,
  triggerDriftDetection,
  triggerEvaluation,
  type EvaluationResult,
  type DriftDetectionResult,
} from "@/lib/monitoring-api";
import type {
  DriftTimelineResponse,
  MonitoringAlertsResponse,
  MonitoringSummary,
  PerformanceTimelineResponse,
  VersionComparisonResponse,
} from "@/lib/monitoring-api";
import { getRegisteredModels } from "@/lib/models-api";
import type { RegisteredModel } from "@/lib/models-api";
import { Card } from "@/components/common/primitives";
import { Icon } from "@/components/common/icons";
import { OverviewTab } from "@/components/features/monitoring/overview-tab";
import { PerformanceTab } from "@/components/features/monitoring/performance-tab";
import { DriftTab } from "@/components/features/monitoring/drift-tab";
import { ComparisonTab } from "@/components/features/monitoring/comparison-tab";
import { AlertsTab } from "@/components/features/monitoring/alerts-tab";

type TabKey = "overview" | "performance" | "drift" | "comparison" | "alerts";

const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "performance", label: "Performance" },
  { key: "drift", label: "Drift" },
  { key: "comparison", label: "Comparison" },
  { key: "alerts", label: "Alerts" },
];

export default function MonitoringPage() {
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [summary, setSummary] = useState<MonitoringSummary | null>(null);
  const [performance, setPerformance] = useState<PerformanceTimelineResponse | null>(null);
  const [drift, setDrift] = useState<DriftTimelineResponse | null>(null);
  const [alerts, setAlerts] = useState<MonitoringAlertsResponse | null>(null);
  const [comparison, setComparison] = useState<VersionComparisonResponse | null>(null);
  const [compareVersionA, setCompareVersionA] = useState("");
  const [compareVersionB, setCompareVersionB] = useState("");

  const [actionLoading, setActionLoading] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionResult, setActionResult] = useState<EvaluationResult | DriftDetectionResult | null>(null);

  // Track the current loading controller so we can cancel it
  const loadControllerRef = useRef<AbortController | null>(null);

  // Load model list (once)
  useEffect(() => {
    const ctrl = new AbortController();
    getRegisteredModels(ctrl.signal)
      .then((data) => {
        setModels(data.models);
        if (!selectedModel && data.models.length > 0) setSelectedModel(data.models[0].name);
      })
      .catch((err) => { if (!ctrl.signal.aborted) setError(err instanceof Error ? err.message : "Failed to load models"); });
    return () => ctrl.abort();
  }, []);

  // Internal data loader (cancels previous load)
  const doLoad = useCallback(async (modelName: string, tab: TabKey) => {
    loadControllerRef.current?.abort();
    const ctrl = new AbortController();
    loadControllerRef.current = ctrl;

    setLoading(true);
    setError(null);
    setActionResult(null);

    try {
      if (tab === "overview" || tab === "performance") {
        const [s, p] = await Promise.all([
          getMonitoringSummary(modelName, undefined, ctrl.signal).catch(() => null),
          getPerformanceTimeline(modelName, undefined, ctrl.signal).catch(() => null),
        ]);
        if (!ctrl.signal.aborted) { setSummary(s); setPerformance(p); }
      }
      if (tab === "drift" && !ctrl.signal.aborted) {
        const d = await getDriftTimeline(modelName, undefined, ctrl.signal);
        if (!ctrl.signal.aborted) setDrift(d);
      }
      if (tab === "alerts" && !ctrl.signal.aborted) {
        const a = await getMonitoringAlerts(modelName, undefined, ctrl.signal);
        if (!ctrl.signal.aborted) setAlerts(a);
      }
      if (tab === "comparison" && compareVersionA && compareVersionB && !ctrl.signal.aborted) {
        const c = await compareVersions(modelName, compareVersionA, compareVersionB, undefined, ctrl.signal);
        if (!ctrl.signal.aborted) setComparison(c);
      }
    } catch (err) {
      if (!ctrl.signal.aborted) setError(err instanceof Error ? err.message : "Failed to load monitoring data");
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, [compareVersionA, compareVersionB]);

  // Reload when model or tab changes
  useEffect(() => {
    if (selectedModel) doLoad(selectedModel, activeTab);
    return () => { loadControllerRef.current?.abort(); };
  }, [selectedModel, activeTab, doLoad]);

  const selectedModelData = useMemo(() => models.find((m) => m.name === selectedModel), [models, selectedModel]);
  const availableVersions = useMemo(() => {
    if (!selectedModelData) return [];
    const v: string[] = [];
    if (selectedModelData.production_version) v.push(selectedModelData.production_version.version);
    for (const ver of selectedModelData.latest_versions) if (!v.includes(ver.version)) v.push(ver.version);
    return v;
  }, [selectedModelData]);

  const handleAction = async (action: "evaluate" | "drift") => {
    if (!selectedModel) return;
    setActionLoading(true);
    setActionMessage(null);
    setActionResult(null);
    try {
      if (action === "evaluate") {
        const result = await triggerEvaluation(selectedModel);
        const count = result.evaluated_models?.length ?? 0;
        setActionMessage(count > 0
          ? `Evaluation complete — ${count} model/version combo(s) processed`
          : "Evaluation complete — no predictions with actuals found. Predictions need actual telemetry to be evaluated.");
        setActionResult(result);
      } else {
        const result = await triggerDriftDetection(selectedModel);
        const count = result.drift_reports?.length ?? 0;
        setActionMessage(count > 0
          ? `Drift detection complete — ${count} report(s) generated`
          : "Drift detection complete — no drift reports generated. Need at least 10 prediction logs with errors (concept drift) or 20+ predictions (prediction drift).");
        setActionResult(result);
      }

      // Reload data after action, properly awaited
      loadControllerRef.current?.abort();
      await doLoad(selectedModel, activeTab);
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : "Action failed");
    } finally {
      setActionLoading(false);
    }
  };

  const isSuccess = actionMessage != null && !actionMessage.includes("failed") && !actionMessage.includes("Failed");

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Model Monitoring</h1>
          <p className="page-sub">Track model performance, detect drift, and monitor health scores across your ML models</p>
        </div>
      </div>

      {/* Selector bar */}
      <div style={{ marginBottom: "var(--gap)" }}>
        <Card title="Model" sub="Select a model to monitor" actions={
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <div className="seg">
              {TABS.map((tab) => (
                <button key={tab.key} className={activeTab === tab.key ? "on" : ""} onClick={() => setActiveTab(tab.key)}>
                  {tab.label}
                </button>
              ))}
            </div>
            <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} style={modelSelectStyle}>
              {models.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
            </select>
            <button className="btn btn-sm btn-primary" onClick={() => handleAction("evaluate")} disabled={actionLoading}>
              <Icon name="refresh" /> Evaluate
            </button>
            <button className="btn btn-sm btn-ghost" onClick={() => handleAction("drift")} disabled={actionLoading}>
              <Icon name="pulse" /> Detect Drift
            </button>
          </div>
        } noBody />
      </div>

      {/* Action feedback */}
      {actionMessage && (
        <div style={{ padding: "10px 14px", borderRadius: "var(--radius-sm)", marginBottom: "var(--gap)", background: isSuccess ? "var(--green-soft)" : "var(--red-soft)", color: isSuccess ? "var(--green)" : "var(--red)", fontSize: 12.5, fontWeight: 500 }}>
          {actionMessage}
        </div>
      )}

      {/* Action result details */}
      {actionResult && (
        <Card title="Last Action Result" icon="check" sub="Details from the most recent evaluation or drift detection">
          <pre style={{ background: "var(--surface-3)", padding: 12, borderRadius: 6, fontSize: 12, overflow: "auto", maxHeight: 200, fontFamily: "var(--font-mono)", lineHeight: 1.6 }}>
            {JSON.stringify(actionResult, null, 2)}
          </pre>
        </Card>
      )}

      {/* Error */}
      {error && (
        <div style={{ padding: "10px 14px", borderRadius: "var(--radius-sm)", marginBottom: "var(--gap)", background: "var(--red-soft)", color: "var(--red)", fontSize: 12.5, fontWeight: 500 }}>
          {error}
        </div>
      )}

      {/* Empty state when nothing found */}
      {!loading && !error && activeTab === "overview" && !summary && (
        <Card title="No Monitoring Data" icon="alert" sub="The model has no prediction logs with actuals yet">
          <div style={{ padding: "8px 0", fontSize: 13, lineHeight: 1.7, color: "var(--ink-2)" }}>
            <p style={{ margin: 0 }}>
              Monitoring requires <b>prediction logs with actual telemetry values</b> to compute metrics.
              The evaluation engine only processes predictions where the actual value has been filled in by the Celery background task.
            </p>
            <p style={{ margin: "8px 0 0" }}>
              <b>What to do:</b>
            </p>
            <ol style={{ margin: "4px 0 0", paddingLeft: 20 }}>
              <li>Make some predictions via the <b>Forecasting</b> or <b>Prediction</b> pages</li>
              <li>Wait for actual telemetry to arrive (or run the <code>fill_actuals</code> Celery task)</li>
              <li>Click <b>Evaluate</b> again to compute performance metrics</li>
            </ol>
          </div>
        </Card>
      )}

      {!loading && !error && activeTab === "drift" && (!drift || (drift.overall_drift.length === 0 && Object.keys(drift.feature_drift || {}).length === 0)) && (
        <Card title="No Drift Data" icon="alert" sub="No drift reports found for this model">
          <div style={{ padding: "8px 0", fontSize: 13, lineHeight: 1.7, color: "var(--ink-2)" }}>
            <p style={{ margin: 0 }}>
              Drift detection requires <b>prediction logs with feature values</b> to compare against reference distributions.
            </p>
            <p style={{ margin: "8px 0 0" }}>
              <b>What to do:</b>
            </p>
            <ol style={{ margin: "4px 0 0", paddingLeft: 20 }}>
              <li>Make predictions to populate the <code>prediction_log</code> table</li>
              <li>Ensure the model has reference stats stored in MLflow during training</li>
              <li>Click <b>Detect Drift</b> to run the PSI and KS tests</li>
            </ol>
          </div>
        </Card>
      )}

      {/* Content */}
      {loading ? (
        <div style={{ textAlign: "center", padding: 60, color: "var(--muted)" }}>
          <div style={{ fontSize: 14 }}>Loading monitoring data&#8230;</div>
        </div>
      ) : (
        <>
          {!actionResult && activeTab === "overview" && summary && <OverviewTab summary={summary} />}
          {!actionResult && activeTab === "performance" && performance && <PerformanceTab data={performance} />}
          {!actionResult && activeTab === "drift" && drift && (drift.overall_drift.length > 0 || Object.keys(drift.feature_drift).length > 0) && <DriftTab data={drift} />}
          {!actionResult && activeTab === "comparison" && (
            <ComparisonTab
              versions={availableVersions}
              versionA={compareVersionA}
              versionB={compareVersionB}
              onChangeA={setCompareVersionA}
              onChangeB={setCompareVersionB}
              data={comparison}
              onCompare={() => { if (selectedModel && compareVersionA && compareVersionB) doLoad(selectedModel, "comparison"); }}
            />
          )}
          {!actionResult && activeTab === "alerts" && alerts && <AlertsTab data={alerts} />}
        </>
      )}
    </div>
  );
}

const modelSelectStyle: React.CSSProperties = { padding: "6px 10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--ink)", fontSize: 12.5, fontFamily: "var(--font-sans)" };
