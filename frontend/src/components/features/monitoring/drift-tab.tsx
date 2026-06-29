"use client";

import { useMemo } from "react";
import type { DriftTimelineResponse, DriftReport } from "@/lib/monitoring-api";
import { EChart } from "@/components/common/charts";
import { Card } from "@/components/common/primitives";

function sevBg(s: string) {
  return s === "high" ? "var(--red-soft)" : s === "medium" ? "var(--orange-soft)" : s === "low" ? "var(--amber-soft)" : "var(--green-soft)";
}
function sevColor(s: string) {
  return s === "high" ? "var(--red)" : s === "medium" ? "var(--orange)" : s === "low" ? "var(--amber)" : "var(--green)";
}

function DriftTimelineChart({ drifts }: { drifts: { drift_score: number; computed_at: string }[] }) {
  const option = useMemo(() => ({
    tooltip: { trigger: "axis" as const },
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    xAxis: { type: "category" as const, data: drifts.map((d) => new Date(d.computed_at).toLocaleDateString()), axisLabel: { fontSize: 11 } },
    yAxis: { type: "value" as const, splitLine: { lineStyle: { type: "dashed" } } },
    series: [{ name: "Drift Score", type: "bar" as const, data: drifts.map((d) => d.drift_score), itemStyle: { borderRadius: [3, 3, 0, 0] } }],
    visualMap: {
      show: false,
      pieces: [
        { gt: 0, lte: 0.1, color: "var(--green)" },
        { gt: 0.1, lte: 0.2, color: "var(--amber)" },
        { gt: 0.2, lte: 0.25, color: "var(--orange)" },
        { gt: 0.25, color: "var(--red)" },
      ],
    },
  }), [drifts]);
  return <EChart build={() => option} height={220} />;
}

const ROW: React.CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 0", borderBottom: "1px solid var(--surface-3)" };
const TH: React.CSSProperties = { textAlign: "left", padding: "8px 10px", fontSize: 11.5, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".04em" };
const TD: React.CSSProperties = { padding: "9px 10px", fontSize: 13 };

export function DriftTab({ data }: { data: DriftTimelineResponse | null }) {
  if (!data) return <div style={{ textAlign: "center", padding: 40, color: "var(--muted)" }}>No drift data available. Trigger drift detection to analyze.</div>;

  const featureEntries = Object.entries(data.feature_drift);

  return (
    <div className="grid" style={{ gap: "var(--gap)" }}>
      {data.overall_drift.length > 0 && (
        <Card title="Drift Score Timeline" icon="alert" sub="Overall drift across all features">
          <DriftTimelineChart drifts={data.overall_drift} />
        </Card>
      )}
      {featureEntries.length > 0 && (
        <Card title="Feature Drift Scores" icon="table" sub={`${featureEntries.length} features analyzed`}>
          <div style={{ overflow: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  <th style={TH}>Feature</th>
                  <th style={{ ...TH, textAlign: "center" }}>Type</th>
                  <th style={{ ...TH, textAlign: "center" }}>Score</th>
                  <th style={{ ...TH, textAlign: "center" }}>Severity</th>
                  <th style={{ ...TH, textAlign: "center" }}>Drifted</th>
                  <th style={{ ...TH, textAlign: "right" }}>Date</th>
                </tr>
              </thead>
              <tbody>
                {featureEntries.map(([feature, ds]) =>
                  ds.slice(0, 5).map((d: DriftReport) => (
                    <tr key={d.id} style={{ borderBottom: "1px solid var(--surface-3)" }}>
                      <td style={{ ...TD, fontWeight: 600 }}>{feature}</td>
                      <td style={{ ...TD, textAlign: "center", color: "var(--muted)" }}>{d.drift_type.replace(/_/g, " ")}</td>
                      <td style={{ ...TD, textAlign: "center" }} className="mono">{d.drift_score.toFixed(4)}</td>
                      <td style={{ ...TD, textAlign: "center" }}>
                        <span style={{ padding: "3px 10px", borderRadius: 8, fontSize: 11.5, fontWeight: 600, background: sevBg(d.severity), color: sevColor(d.severity) }}>{d.severity}</span>
                      </td>
                      <td style={{ ...TD, textAlign: "center" }}>{d.is_drifted ? <span style={{ color: "var(--orange)" }}>Yes</span> : <span style={{ color: "var(--green)" }}>No</span>}</td>
                      <td style={{ ...TD, textAlign: "right", color: "var(--muted)", fontSize: 11.5 }}>{new Date(d.computed_at).toLocaleDateString()}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {data.overall_drift.length === 0 && featureEntries.length === 0 && (
        <div style={{ textAlign: "center", padding: 40, color: "var(--muted)" }}>No drift detected for this model.</div>
      )}
    </div>
  );
}
