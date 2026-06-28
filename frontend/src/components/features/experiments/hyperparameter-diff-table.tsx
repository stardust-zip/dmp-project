"use client";

import type { ExperimentVersionDetail } from "@/lib/experiments-api";

// ---------------------------------------------------------------------------
// Sub-types
// ---------------------------------------------------------------------------

type DiffIndicator = "up" | "down" | "same" | "baseline";

interface CellDiff {
  value: string | undefined;
  indicator: DiffIndicator;
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

function parseMaybeFloat(raw: string | undefined): number | null {
  if (raw == null) return null;
  const parsed = parseFloat(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function computeDiffIndicator(
  baselineRaw: string | undefined,
  currentRaw: string | undefined,
  isBaseline: boolean,
): DiffIndicator {
  if (isBaseline) return "baseline";
  const baseline = parseMaybeFloat(baselineRaw);
  const current = parseMaybeFloat(currentRaw);
  if (baseline == null || current == null || baseline === current) return "same";
  return current > baseline ? "up" : "down";
}

function buildCellDiff(
  key: string,
  versionDetails: ExperimentVersionDetail[],
  versionIndex: number,
): CellDiff {
  const value = versionDetails[versionIndex].hyperparameters[key];
  const indicator = computeDiffIndicator(
    versionDetails[0].hyperparameters[key],
    value,
    versionIndex === 0,
  );
  return { value, indicator };
}

function collectAllHyperparameterKeys(
  versionDetails: ExperimentVersionDetail[],
): string[] {
  const keySet = new Set(
    versionDetails.flatMap((v) => Object.keys(v.hyperparameters)),
  );
  return [...keySet].sort();
}

// ---------------------------------------------------------------------------
// Presentational sub-components
// ---------------------------------------------------------------------------

const TH: React.CSSProperties = {
  textAlign: "left",
  padding: "9px 12px",
  fontSize: 11.5,
  fontWeight: 600,
  color: "var(--muted)",
  textTransform: "uppercase",
  letterSpacing: ".04em",
  borderBottom: "1px solid var(--border)",
  whiteSpace: "nowrap",
};

const TD: React.CSSProperties = {
  padding: "9px 12px",
  fontSize: 13,
  borderBottom: "1px solid var(--surface-3)",
};

function DiffBadge({ indicator }: { indicator: DiffIndicator }) {
  if (indicator === "baseline" || indicator === "same") return null;
  const isUp = indicator === "up";
  return (
    <span
      style={{
        marginLeft: 6,
        fontSize: 10,
        fontWeight: 700,
        color: isUp ? "var(--orange)" : "var(--accent-600)",
      }}
    >
      {isUp ? "▴" : "▾"}
    </span>
  );
}

function VersionCell({ cell, isBaseline }: { cell: CellDiff; isBaseline: boolean }) {
  return (
    <td
      className="mono"
      style={{
        ...TD,
        textAlign: "center",
        background: isBaseline ? "var(--surface-3)" : undefined,
      }}
    >
      {cell.value ?? <span style={{ color: "var(--muted)" }}>—</span>}
      <DiffBadge indicator={cell.indicator} />
    </td>
  );
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export function HyperparameterDiffTable({
  versionDetails,
}: {
  versionDetails: ExperimentVersionDetail[];
}) {
  const allKeys = collectAllHyperparameterKeys(versionDetails);

  if (allKeys.length === 0) {
    return (
      <div style={{ padding: "16px 0", color: "var(--muted)", fontSize: 13 }}>
        No hyperparameters recorded in MLflow for these versions.
      </div>
    );
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>
            <th style={TH}>Hyperparameter</th>
            {versionDetails.map((v, idx) => (
              <th
                key={v.version}
                style={{
                  ...TH,
                  textAlign: "center",
                  background: idx === 0 ? "var(--surface-3)" : undefined,
                }}
              >
                v{v.version}
                {idx === 0 && (
                  <span
                    style={{
                      marginLeft: 6,
                      fontSize: 10,
                      color: "var(--muted)",
                      fontWeight: 400,
                      textTransform: "none",
                    }}
                  >
                    (baseline)
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {allKeys.map((key) => (
            <tr key={key}>
              <td style={{ ...TD, fontWeight: 500 }}>{key}</td>
              {versionDetails.map((_, idx) => (
                <VersionCell
                  key={idx}
                  cell={buildCellDiff(key, versionDetails, idx)}
                  isBaseline={idx === 0}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div
        style={{
          marginTop: 10,
          fontSize: 11.5,
          color: "var(--muted)",
          display: "flex",
          gap: 16,
        }}
      >
        <span>
          <span style={{ color: "var(--orange)", fontWeight: 700 }}>▴</span> higher than baseline
        </span>
        <span>
          <span style={{ color: "var(--accent-600)", fontWeight: 700 }}>▾</span> lower than baseline
        </span>
      </div>
    </div>
  );
}
