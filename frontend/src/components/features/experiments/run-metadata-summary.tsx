"use client";

import type { ExperimentVersionDetail } from "@/lib/experiments-api";

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

function formatEpochMs(epochMs: number | null): string {
  if (epochMs == null) return "—";
  return new Date(epochMs).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function computeRuntimeSeconds(startMs: number | null, endMs: number | null): string {
  if (startMs == null || endMs == null) return "—";
  const seconds = Math.round((endMs - startMs) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds}s`;
}

function stageBadgeStyle(stage: string | null): React.CSSProperties {
  const normalized = (stage ?? "").toLowerCase();
  if (normalized === "production") return { color: "var(--green)", background: "var(--green-soft)" };
  if (normalized === "staging") return { color: "var(--orange)", background: "var(--orange-soft)" };
  return { color: "var(--muted)", background: "var(--surface-3)" };
}

function statusBadgeStyle(runStatus: string | null): React.CSSProperties {
  const normalized = (runStatus ?? "").toUpperCase();
  if (normalized === "FINISHED") return { color: "var(--green)", background: "var(--green-soft)" };
  if (normalized === "FAILED" || normalized === "KILLED") return { color: "var(--red)", background: "var(--red-soft)" };
  return { color: "var(--muted)", background: "var(--surface-3)" };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const BADGE_STYLE: React.CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 20,
  fontSize: 11,
  fontWeight: 600,
};

const ROW_LABEL: React.CSSProperties = {
  fontSize: 11,
  color: "var(--muted)",
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: ".04em",
  minWidth: 100,
};

const ROW_VALUE: React.CSSProperties = {
  fontSize: 12.5,
  color: "var(--ink)",
  fontWeight: 500,
};

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "flex-start", marginBottom: 8 }}>
      <span style={ROW_LABEL}>{label}</span>
      <span style={ROW_VALUE}>{children}</span>
    </div>
  );
}

function RunCard({ detail }: { detail: ExperimentVersionDetail }) {
  return (
    <div
      style={{
        flex: "1 1 220px",
        minWidth: 200,
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
          marginBottom: 12,
          textTransform: "uppercase",
          letterSpacing: ".04em",
        }}
      >
        v{detail.version}
      </div>

      <MetaRow label="Stage">
        <span style={{ ...BADGE_STYLE, ...stageBadgeStyle(detail.current_stage) }}>
          {detail.current_stage ?? "None"}
        </span>
      </MetaRow>

      <MetaRow label="Run Status">
        <span style={{ ...BADGE_STYLE, ...statusBadgeStyle(detail.run_status) }}>
          {detail.run_status ?? "—"}
        </span>
      </MetaRow>

      <MetaRow label="Algorithm">{detail.algorithm ?? "—"}</MetaRow>
      <MetaRow label="Task">{detail.model_task ?? "—"}</MetaRow>

      <MetaRow label="Started">{formatEpochMs(detail.run_start_time)}</MetaRow>
      <MetaRow label="Runtime">
        {computeRuntimeSeconds(detail.run_start_time, detail.run_end_time)}
      </MetaRow>

      <MetaRow label="Run ID">
        <span
          className="mono"
          style={{ fontSize: 11, color: "var(--muted)", wordBreak: "break-all" }}
        >
          {detail.run_id.slice(0, 12)}…
        </span>
      </MetaRow>

      {Object.keys(detail.tags).length > 0 && (
        <div style={{ marginTop: 10, borderTop: "1px solid var(--surface-3)", paddingTop: 10 }}>
          <div style={{ ...ROW_LABEL, marginBottom: 6 }}>Tags</div>
          {Object.entries(detail.tags).slice(0, 5).map(([key, value]) => (
            <div
              key={key}
              style={{ display: "flex", gap: 6, marginBottom: 4, fontSize: 12 }}
            >
              <span style={{ color: "var(--muted)" }}>{key}:</span>
              <span style={{ color: "var(--ink)", fontWeight: 500 }}>{value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export function RunMetadataSummary({
  versionDetails,
}: {
  versionDetails: ExperimentVersionDetail[];
}) {
  return (
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
      {versionDetails.map((detail) => (
        <RunCard key={detail.version} detail={detail} />
      ))}
    </div>
  );
}
