"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { compareExperiments } from "@/lib/experiments-api";
import type { ExperimentComparisonResponse } from "@/lib/experiments-api";
import { getRegisteredModels, getModelVersions } from "@/lib/models-api";
import type { RegisteredModel } from "@/lib/models-api";
import { Card } from "@/components/common/primitives";
import { Icon } from "@/components/common/icons";
import { HyperparameterDiffTable } from "@/components/features/experiments/hyperparameter-diff-table";
import { TrainingDataComparison } from "@/components/features/experiments/training-data-comparison";
import { MetricsComparisonCharts } from "@/components/features/experiments/metrics-comparison-charts";
import { RunMetadataSummary } from "@/components/features/experiments/run-metadata-summary";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MIN_VERSIONS = 2;
const MAX_VERSIONS = 10;

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

function toggleVersionInSelection(
  selected: string[],
  version: string,
): string[] {
  const isAlreadySelected = selected.includes(version);
  if (isAlreadySelected) {
    return selected.filter((v) => v !== version);
  }
  if (selected.length >= MAX_VERSIONS) return selected;
  return [...selected, version];
}

function isCompareReady(selectedVersions: string[]): boolean {
  return selectedVersions.length >= MIN_VERSIONS;
}

// ---------------------------------------------------------------------------
// Version selector sub-component
// ---------------------------------------------------------------------------

function VersionCheckboxList({
  availableVersions,
  selectedVersions,
  onToggle,
}: {
  availableVersions: string[];
  selectedVersions: string[];
  onToggle: (version: string) => void;
}) {
  if (availableVersions.length === 0) {
    return (
      <div style={{ color: "var(--muted)", fontSize: 13 }}>
        No versions found for this model.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {availableVersions.map((version) => {
        const isChecked = selectedVersions.includes(version);
        return (
          <label
            key={version}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              cursor: "pointer",
              padding: "6px 12px",
              borderRadius: "var(--radius-sm)",
              border: `1px solid ${isChecked ? "var(--accent-600)" : "var(--border)"}`,
              background: isChecked ? "var(--accent-soft)" : "var(--surface)",
              fontSize: 13,
              fontWeight: isChecked ? 600 : 400,
              color: isChecked ? "var(--accent-600)" : "var(--ink)",
              userSelect: "none",
            }}
          >
            <input
              type="checkbox"
              checked={isChecked}
              onChange={() => onToggle(version)}
              style={{ accentColor: "var(--accent-600)", width: 14, height: 14 }}
            />
            v{version}
          </label>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Comparison result sections
// ---------------------------------------------------------------------------

type SectionKey = "metrics" | "hyperparameters" | "training" | "metadata";

const SECTIONS: { key: SectionKey; label: string; icon: "gauge" | "sliders" | "table" | "info" }[] = [
  { key: "metrics", label: "Evaluation Metrics", icon: "gauge" },
  { key: "hyperparameters", label: "Hyperparameters", icon: "sliders" },
  { key: "training", label: "Training Data", icon: "table" },
  { key: "metadata", label: "Run Metadata", icon: "info" },
];

function ComparisonResults({
  data,
}: {
  data: ExperimentComparisonResponse;
}) {
  const [activeSection, setActiveSection] = useState<SectionKey>("metrics");

  return (
    <div style={{ marginTop: "var(--gap)" }}>
      {/* Section switcher */}
      <div style={{ display: "flex", gap: 6, marginBottom: "var(--gap)", flexWrap: "wrap" }}>
        {SECTIONS.map((section) => (
          <button
            key={section.key}
            className={`btn btn-sm ${activeSection === section.key ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setActiveSection(section.key)}
          >
            <Icon name={section.icon} style={{ width: 14, height: 14 }} />
            {section.label}
          </button>
        ))}
      </div>

      {activeSection === "metrics" && (
        <Card title="Evaluation Metrics" icon="gauge" sub="Side-by-side comparison of post-deployment evaluation metrics">
          <MetricsComparisonCharts
            versionDetails={data.versions}
            commonMetrics={data.common_metrics}
          />
        </Card>
      )}

      {activeSection === "hyperparameters" && (
        <Card title="Hyperparameter Diff" icon="sliders" sub="All hyperparameter values — ▴/▾ indicate change from the baseline (first) version">
          <HyperparameterDiffTable versionDetails={data.versions} />
        </Card>
      )}

      {activeSection === "training" && (
        <Card title="Training Data Attributes" icon="table" sub="Dataset footprint derived from MLflow tags and prediction logs">
          <TrainingDataComparison versionDetails={data.versions} />
        </Card>
      )}

      {activeSection === "metadata" && (
        <Card title="Run Metadata" icon="info" sub="Algorithm, runtime, stage, and MLflow run info per version">
          <RunMetadataSummary versionDetails={data.versions} />
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Top-level page component
// ---------------------------------------------------------------------------

export function ExperimentComparisonPage() {
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [availableVersions, setAvailableVersions] = useState<string[]>([]);
  const [selectedVersions, setSelectedVersions] = useState<string[]>([]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [comparisonData, setComparisonData] = useState<ExperimentComparisonResponse | null>(null);

  const loadControllerRef = useRef<AbortController | null>(null);

  // Load registered model list once on mount
  useEffect(() => {
    const ctrl = new AbortController();
    getRegisteredModels(ctrl.signal)
      .then((data) => {
        setModels(data.models);
        if (data.models.length > 0) setSelectedModel(data.models[0].name);
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) {
          setError(err instanceof Error ? err.message : "Failed to load model list");
        }
      });
    return () => ctrl.abort();
  }, []);

  // Reload version list whenever selected model changes
  useEffect(() => {
    if (!selectedModel) return;
    setAvailableVersions([]);
    setSelectedVersions([]);
    setComparisonData(null);

    const ctrl = new AbortController();
    getModelVersions(selectedModel, ctrl.signal)
      .then((data) => {
        setAvailableVersions(data.versions.map((v) => v.version));
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setAvailableVersions([]);
      });
    return () => ctrl.abort();
  }, [selectedModel]);

  // Clear stale results when version selection changes
  useEffect(() => {
    setComparisonData(null);
    setError(null);
  }, [selectedVersions, selectedModel]);

  const handleToggleVersion = useCallback((version: string) => {
    setSelectedVersions((prev) => toggleVersionInSelection(prev, version));
  }, []);

  const handleCompare = useCallback(async () => {
    if (!isCompareReady(selectedVersions)) return;

    loadControllerRef.current?.abort();
    const ctrl = new AbortController();
    loadControllerRef.current = ctrl;

    setLoading(true);
    setError(null);
    setComparisonData(null);

    try {
      const data = await compareExperiments(selectedModel, selectedVersions, {}, ctrl.signal);
      if (!ctrl.signal.aborted) setComparisonData(data);
    } catch (err) {
      if (!ctrl.signal.aborted) {
        setError(err instanceof Error ? err.message : "Comparison failed");
      }
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, [selectedModel, selectedVersions]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Experiment Comparison</h1>
          <p className="page-sub">
            Compare hyperparameters, training data, and evaluation metrics across 2–10 model versions
          </p>
        </div>
      </div>

      {/* Model + version selection */}
      <Card
        title="Select Model & Versions"
        icon="sliders"
        sub="Pick a model and check 2–10 versions to compare side by side"
        actions={
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              style={SELECT_STYLE}
            >
              {models.length === 0 && (
                <option value="" disabled>Loading models…</option>
              )}
              {models.map((m) => (
                <option key={m.name} value={m.name}>{m.name}</option>
              ))}
            </select>
            <button
              className="btn btn-sm btn-primary"
              onClick={handleCompare}
              disabled={!isCompareReady(selectedVersions) || loading}
            >
              {loading ? (
                <>
                  <Icon name="refresh" className="spin" style={{ width: 14, height: 14 }} />
                  Comparing…
                </>
              ) : (
                <>
                  <Icon name="layers" style={{ width: 14, height: 14 }} />
                  Compare ({selectedVersions.length})
                </>
              )}
            </button>
          </div>
        }
      >
        <VersionCheckboxList
          availableVersions={availableVersions}
          selectedVersions={selectedVersions}
          onToggle={handleToggleVersion}
        />
        {selectedVersions.length > 0 && !isCompareReady(selectedVersions) && (
          <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--orange)" }}>
            Select at least {MIN_VERSIONS} versions to enable comparison.
          </div>
        )}
      </Card>

      {/* Error banner */}
      {error && (
        <div
          style={{
            marginTop: "var(--gap)",
            padding: "10px 14px",
            borderRadius: "var(--radius-sm)",
            background: "var(--red-soft)",
            color: "var(--red)",
            fontSize: 12.5,
            fontWeight: 500,
          }}
        >
          {error}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div style={{ textAlign: "center", padding: 60, color: "var(--muted)" }}>
          <Icon name="refresh" className="spin" style={{ width: 22, height: 22, marginBottom: 8 }} />
          <div style={{ fontSize: 14 }}>Loading comparison data…</div>
        </div>
      )}

      {/* Comparison results */}
      {!loading && comparisonData && (
        <ComparisonResults data={comparisonData} />
      )}

      {/* Empty state — nothing compared yet */}
      {!loading && !comparisonData && !error && selectedVersions.length === 0 && (
        <div
          style={{
            marginTop: "var(--gap)",
            padding: "32px 24px",
            textAlign: "center",
            color: "var(--muted)",
            fontSize: 13,
            border: "1px dashed var(--border)",
            borderRadius: "var(--radius)",
          }}
        >
          <Icon name="layers" style={{ width: 32, height: 32, marginBottom: 12, opacity: 0.35 }} />
          <div>Select 2–10 versions above and click <b>Compare</b> to begin.</div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const SELECT_STYLE: React.CSSProperties = {
  padding: "6px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border)",
  background: "var(--surface)",
  color: "var(--ink)",
  fontSize: 12.5,
  fontFamily: "var(--font-sans)",
};
