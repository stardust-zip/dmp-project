"use client";

import { useState, useMemo } from "react";
import type { MonitoringAlertsResponse } from "@/lib/monitoring-api";
import { Card } from "@/components/common/primitives";

function sevBg(s: string) {
  return s === "critical" || s === "high" ? "var(--red-soft)" : s === "medium" ? "var(--orange-soft)" : "var(--amber-soft)";
}
function sevColor(s: string) {
  return s === "critical" || s === "high" ? "var(--red)" : s === "medium" ? "var(--orange)" : "var(--amber)";
}
function sevDot(s: string) {
  return s === "critical" || s === "high" ? "var(--red)" : s === "medium" ? "var(--orange)" : "var(--amber)";
}

export function AlertsTab({ data }: { data: MonitoringAlertsResponse | null }) {
  const [severityFilter, setSeverityFilter] = useState("");
  const filtered = useMemo(() => {
    if (!data) return [];
    return severityFilter ? data.alerts.filter((a) => a.severity === severityFilter) : data.alerts;
  }, [data, severityFilter]);

  if (!data) return <div style={{ textAlign: "center", padding: 40, color: "var(--muted)" }}>No alerts data available.</div>;

  return (
    <Card
      title="Alert History"
      icon="bell"
      sub={`${data.total} alert${data.total !== 1 ? "s" : ""}`}
      actions={
        <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)} style={selectStyle}>
          <option value="">All Severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      }
    >
      {filtered.length === 0 ? (
        <div style={{ padding: "16px 0", color: "var(--muted)", textAlign: "center" }}>{severityFilter ? `No ${severityFilter} severity alerts` : "No alerts"}</div>
      ) : (
        <div style={{ maxHeight: 480, overflow: "auto" }}>
          {filtered.map((alert) => (
            <div key={alert.id} style={{ padding: "10px 0", borderBottom: "1px solid var(--surface-3)", display: "flex", gap: 12, alignItems: "flex-start" }}>
              <div style={{ width: 7, height: 7, borderRadius: "50%", background: sevDot(alert.severity), marginTop: 5, flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: 13 }}>{alert.drift_type}{alert.feature_name ? ` (${alert.feature_name})` : ""}</span>
                  <span style={{ padding: "2px 9px", borderRadius: 8, fontSize: 11, fontWeight: 600, background: sevBg(alert.severity), color: sevColor(alert.severity), flexShrink: 0 }}>{alert.severity}</span>
                </div>
                {alert.message && <div style={{ color: "var(--muted)", marginTop: 3, fontSize: 12 }}>{alert.message}</div>}
                <div style={{ color: "var(--muted)", marginTop: 4, fontSize: 11 }} className="mono">score: {alert.drift_score.toFixed(4)} &middot; {new Date(alert.computed_at).toLocaleString()}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

const selectStyle: React.CSSProperties = { padding: "4px 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--ink)", fontSize: 12, fontFamily: "var(--font-sans)" };
