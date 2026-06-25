"use client";

import type { VersionComparisonResponse } from "@/lib/monitoring-api";
import { Card } from "@/components/common/primitives";

const TH: React.CSSProperties = { textAlign: "left", padding: "9px 10px", fontSize: 11.5, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".04em" };
const TD: React.CSSProperties = { padding: "9px 10px", fontSize: 13 };

export function ComparisonTab({
  versions, versionA, versionB, onChangeA, onChangeB, data, onCompare, loading,
}: {
  versions: string[]; versionA: string; versionB: string;
  onChangeA: (v: string) => void; onChangeB: (v: string) => void;
  data: VersionComparisonResponse | null; onCompare: () => void;
  loading?: boolean;
}) {
  return (
    <Card title="Version Comparison" icon="layers" sub="Compare metrics between two model versions">
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16 }}>
        <select value={versionA} onChange={(e) => onChangeA(e.target.value)} style={selectStyle}>
          <option value="" disabled>Select version…</option>
          {versions.map((v) => <option key={v} value={v}>v{v}</option>)}
        </select>
        <span style={{ color: "var(--muted)", fontSize: 12 }}>vs</span>
        <select value={versionB} onChange={(e) => onChangeB(e.target.value)} style={selectStyle}>
          <option value="" disabled>Select version…</option>
          {versions.map((v) => <option key={v} value={v}>v{v}</option>)}
        </select>
        <button className="btn btn-sm btn-primary" onClick={onCompare} disabled={!versionA || !versionB || loading}>
          {loading ? "Comparing…" : "Compare"}
        </button>
      </div>

      {loading && (
        <div style={{ textAlign: "center", padding: 32, color: "var(--muted)", fontSize: 13 }}>
          Loading comparison data&#8230;
        </div>
      )}

      {!loading && data && data.versions.length < 2 && (
        <div style={{ padding: 16, color: "var(--muted)", fontSize: 13, textAlign: "center" }}>
          Select two different versions to compare.
        </div>
      )}

      {!loading && data && data.versions.length === 2 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <th style={TH}>Metric</th>
              <th style={{ ...TH, textAlign: "center" }}>v{data.versions[0].version}</th>
              <th style={{ ...TH, textAlign: "center" }}>v{data.versions[1].version}</th>
              <th style={{ ...TH, textAlign: "center" }}>Diff</th>
            </tr>
          </thead>
          <tbody>
            {["mae", "rmse", "mape", "r2_score", "performance_ratio"].map((metric) => {
              const a = data.versions[0][metric as keyof typeof data.versions[0]] as number | null;
              const b = data.versions[1][metric as keyof typeof data.versions[1]] as number | null;
              const diff = a != null && b != null ? b - a : null;
              const dc = diff != null ? (diff < 0 ? "var(--green)" : diff > 0 && metric !== "r2_score" ? "var(--red)" : "var(--green)") : "var(--muted)";
              return (
                <tr key={metric} style={{ borderBottom: "1px solid var(--surface-3)" }}>
                  <td style={{ ...TD, fontWeight: 600, textTransform: "capitalize" }}>{metric.replace(/_/g, " ")}</td>
                  <td style={{ ...TD, textAlign: "center" }} className="mono">{a != null ? a.toFixed(4) : "—"}</td>
                  <td style={{ ...TD, textAlign: "center" }} className="mono">{b != null ? b.toFixed(4) : "—"}</td>
                  <td className="mono" style={{ ...TD, textAlign: "center", color: dc }}>
                    {diff != null ? `${diff > 0 ? "+" : ""}${diff.toFixed(4)}` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}

const selectStyle: React.CSSProperties = { padding: "6px 10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--ink)", fontSize: 12.5, fontFamily: "var(--font-sans)" };
