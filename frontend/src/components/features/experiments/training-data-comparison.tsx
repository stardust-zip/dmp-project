"use client";

import type { ExperimentVersionDetail } from "@/lib/experiments-api";

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

function formatDateRange(start: string | null, end: string | null): string {
  if (!start && !end) return "—";
  const fmt = (iso: string) =>
    new Date(iso).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  if (start && end) return `${fmt(start)} → ${fmt(end)}`;
  return start ? `from ${fmt(start)}` : `until ${fmt(end!)}`;
}

function formatCount(value: number | null, unit: string): string {
  if (value == null) return "—";
  return `${value.toLocaleString()} ${unit}`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const LABEL_STYLE: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  color: "var(--muted)",
  textTransform: "uppercase",
  letterSpacing: ".04em",
  marginBottom: 4,
};

const VALUE_STYLE: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  color: "var(--ink)",
};

const SUB_STYLE: React.CSSProperties = {
  fontSize: 11.5,
  color: "var(--muted)",
  marginTop: 2,
};

function DataAttribute({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={LABEL_STYLE}>{label}</div>
      <div style={VALUE_STYLE}>{value}</div>
      {sub && <div style={SUB_STYLE}>{sub}</div>}
    </div>
  );
}

function VersionCard({ detail }: { detail: ExperimentVersionDetail }) {
  return (
    <div
      style={{
        flex: "1 1 200px",
        minWidth: 180,
        padding: "14px 16px",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        background: "var(--surface)",
      }}
    >
      <div
        style={{
          fontSize: 12.5,
          fontWeight: 700,
          color: "var(--accent-600)",
          marginBottom: 14,
          textTransform: "uppercase",
          letterSpacing: ".04em",
        }}
      >
        v{detail.version}
      </div>

      <DataAttribute
        label="Data Source"
        value={detail.training_data_source ?? "—"}
      />
      <DataAttribute
        label="Training Period"
        value={formatDateRange(detail.training_start, detail.training_end)}
      />
      <DataAttribute
        label="Row Count"
        value={detail.training_row_count != null
          ? detail.training_row_count.toLocaleString()
          : "—"}
        sub="predictions logged"
      />
      <DataAttribute
        label="Buildings"
        value={formatCount(detail.training_building_count, "distinct")}
      />
      <DataAttribute
        label="Metric Types"
        value={formatCount(detail.training_metric_count, "distinct")}
      />
      <DataAttribute
        label="Feature Count"
        value={detail.feature_count != null ? String(detail.feature_count) : "—"}
        sub="input features"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export function TrainingDataComparison({
  versionDetails,
}: {
  versionDetails: ExperimentVersionDetail[];
}) {
  return (
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
      {versionDetails.map((detail) => (
        <VersionCard key={detail.version} detail={detail} />
      ))}
    </div>
  );
}
