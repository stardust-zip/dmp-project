"use client";

import type { MonitoringSummary } from "@/lib/monitoring-api";
import { Card } from "@/components/common/primitives";

export function OverviewTab({ summary }: { summary: MonitoringSummary | null }) {
  if (!summary) {
    return (
      <div style={{ textAlign: "center", padding: 40, color: "var(--muted)" }}>
        No monitoring data available. Trigger an evaluation to get started.
      </div>
    );
  }

  const statusColor =
    summary.status === "healthy" ? "var(--green)" : summary.status === "degraded" ? "var(--orange)" : "var(--red)";

  const softBg =
    summary.status === "healthy" ? "var(--green-soft)" : summary.status === "degraded" ? "var(--orange-soft)" : "var(--red-soft)";

  return (
    <>
      {/* Top row: Health, Performance, Stats */}
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", marginBottom: "var(--gap)" }}>
        <Card title="Health Score" icon="gauge" sub={`${summary.model_name} v${summary.model_version}`}>
          <div style={{ textAlign: "center", padding: "12px 0" }}>
            <div style={{ fontSize: 52, fontWeight: 700, color: statusColor, lineHeight: 1 }}>
              {summary.health_score.toFixed(0)}
            </div>
            <div style={{ marginTop: 8, padding: "4px 14px", borderRadius: 12, background: softBg, color: statusColor, fontSize: 13, fontWeight: 600, display: "inline-block", letterSpacing: ".04em" }}>
              {summary.status.toUpperCase()}
            </div>
          </div>
        </Card>

        <Card title="Latest Performance" icon="pulse" sub={summary.last_performance ? `Computed ${new Date(summary.last_performance.computed_at).toLocaleDateString()}` : "No data"}>
          {summary.last_performance ? (
            <div>
              <MetricRow label="MAE" value={summary.last_performance.mae?.toFixed(4)} />
              <MetricRow label="RMSE" value={summary.last_performance.rmse?.toFixed(4)} />
              <MetricRow label="MAPE" value={summary.last_performance.mape ? `${summary.last_performance.mape.toFixed(2)}%` : undefined} />
              <MetricRow label="Perf. Ratio" value={summary.last_performance.performance_ratio?.toFixed(2)} />
            </div>
          ) : (
            <div style={{ padding: "16px 0", color: "var(--muted)", textAlign: "center" }}>No performance data</div>
          )}
        </Card>

        <Card title="Prediction Stats" icon="trend" sub="Production metrics">
          <div>
            <MetricRow label="Total Predictions" value={summary.total_predictions.toLocaleString()} />
            <MetricRow label="Pending Actuals" value={summary.pending_actuals.toLocaleString()} />
            <MetricRow label="Active Drifts" value={summary.active_drifts.length.toString()} color={summary.active_drifts.length > 0 ? "var(--orange)" : "var(--green)"} />
          </div>
        </Card>
      </div>

      {/* Active drifts (only if any) */}
      {summary.active_drifts.length > 0 && (
        <Card title="Active Drifts" icon="alert" sub={`${summary.active_drifts.length} drift(s) detected`}>
          <div style={{ maxHeight: 200, overflow: "auto" }}>
            {summary.active_drifts.slice(0, 5).map((d) => (
              <div key={d.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
                <div>
                  <div style={{ fontWeight: 600 }}>{d.drift_type.replace(/_/g, " ")}</div>
                  {d.feature_name && <div style={{ color: "var(--muted)", fontSize: 11.5 }}>{d.feature_name}</div>}
                </div>
                <span style={severityBadge(d.severity)}>{d.severity}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </>
  );
}

function MetricRow({ label, value, color }: { label: string; value?: string; color?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "7px 0", borderBottom: "1px solid var(--surface-3)" }}>
      <span style={{ color: "var(--muted)", fontSize: 12.5 }}>{label}</span>
      <span className="mono" style={{ fontWeight: 600, fontSize: 13, color }}>{value ?? "—"}</span>
    </div>
  );
}

function severityBadge(severity: string): React.CSSProperties {
  const map: Record<string, { bg: string; color: string }> = {
    high: { bg: "var(--red-soft)", color: "var(--red)" },
    medium: { bg: "var(--orange-soft)", color: "var(--orange)" },
    low: { bg: "var(--amber-soft)", color: "var(--amber)" },
  };
  const c = map[severity] ?? { bg: "var(--surface-3)", color: "var(--muted)" };
  return { padding: "3px 10px", borderRadius: 8, fontSize: 11.5, fontWeight: 600, background: c.bg, color: c.color };
}
