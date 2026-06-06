"use client";

import { useState } from "react";
import { buildForecastChart, buildMiniTrend, EChart } from "@/components/common/charts";
import { Icon } from "@/components/common/icons";
import { Card, Select, Spinner, toneStyle } from "@/components/common/primitives";
import { BUILDINGS, FC_KPIS, FORECAST, MODEL_PERF, PERF_TREND } from "@/lib/mock-data";
import { fmt } from "@/lib/format";

type Horizon = "day" | "week" | "month";

function FcKpiCard({ c }: { c: (typeof FC_KPIS)[number] }) {
  const positive = (c.delta ?? 0) > 0;
  const good = c.invertGood ? !positive : positive;
  return (
    <div className="kpi">
      <div className="kpi-top">
        <span className="kpi-label">{c.label}</span>
        <span className="kpi-ic" style={toneStyle(c.tone)}>
          <Icon name={c.icon} />
        </span>
      </div>
      <div className="row" style={{ alignItems: "baseline", gap: 0 }}>
        <span className="kpi-val" style={{ fontSize: c.key === "model" ? 21 : "var(--kpi-val)" }}>{c.value}</span>
        {c.unit && <span className="kpi-unit">{c.unit}</span>}
      </div>
      <div className="kpi-foot">
        {c.delta != null && (
          <span className={`delta ${good ? "down" : "up"}`}>
            <Icon name={positive ? "arrowUp" : "arrowDown"} style={{ width: 12, height: 12 }} />
            {positive ? "+" : ""}{c.delta}{c.key === "mape" ? " pts" : c.unit === "%" ? "%" : c.key === "model" ? "" : "%"}
          </span>
        )}
        {c.delta != null && <span style={{ color: "var(--muted-2)" }}>.</span>}
        <span>{c.text || c.sub}</span>
      </div>
    </div>
  );
}

function ModelPerfCard({ m }: { m: (typeof MODEL_PERF)[number] }) {
  const color = m.tone === "violet" ? "#7c3aed" : m.tone === "green" ? "var(--green)" : "var(--accent-600)";
  const series = PERF_TREND[m.key];
  return (
    <div className="card" style={{ padding: 0 }}>
      <div style={{ padding: "14px 16px 8px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ fontSize: 11.5, color: "var(--muted)", fontWeight: 550 }}>{m.label}</div>
            <div style={{ fontSize: 11, color: "var(--muted-2)" }}>{m.desc}</div>
          </div>
          <span className={`delta ${m.delta < 0 ? "down" : "up"}`} style={{ fontSize: 11 }}>
            <Icon name={m.delta < 0 ? "arrowDown" : "arrowUp"} style={{ width: 11, height: 11 }} />
            {m.delta}{m.unit === "%" ? "pts" : "%"}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 0, marginTop: 8 }}>
          <span className="kpi-val" style={{ fontSize: 24 }}>{m.value}</span>
          <span className="kpi-unit">{m.unit}</span>
        </div>
      </div>
      <EChart build={buildMiniTrend(series, color)} deps={[]} themeKey={m.key} height={44} />
    </div>
  );
}

export function ForecastPage() {
  const [building, setBuilding] = useState("all");
  const [horizon, setHorizon] = useState<Horizon>("week");
  const [toast, setToast] = useState<string | null>(null);
  const rows = FORECAST[horizon];

  const showToast = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 2200);
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Forecasting</h1>
          <p className="page-sub">Forecast future electricity consumption and support capacity planning</p>
        </div>
        <div className="page-head-actions">
          <div style={{ width: 168 }}>
            <Select value={building} onChange={setBuilding} options={[{ value: "all", label: "All Buildings" }, ...BUILDINGS.map((entry) => ({ value: entry.id, label: entry.name }))]} />
          </div>
          <div className="seg">
            {[
              { value: "day", label: "Next Day" },
              { value: "week", label: "Next Week" },
              { value: "month", label: "Next Month" },
            ].map((option) => (
              <button key={option.value} className={horizon === option.value ? "on" : ""} onClick={() => setHorizon(option.value as Horizon)}>
                {option.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))", marginBottom: "var(--gap)" }}>
        {FC_KPIS.map((kpi) => <FcKpiCard key={kpi.key} c={kpi} />)}
      </div>

      <Card
        title="Forecast Visualization"
        icon="trend"
        iconTone="violet"
        sub="Historical consumption with forecast and 95% confidence interval"
        actions={
          <div className="legend">
            <span className="leg" style={{ color: "var(--accent-600)" }}><i style={{ background: "var(--accent-600)" }} /> Historical</span>
            <span className="leg" style={{ color: "#7c3aed" }}><i className="dash" style={{ color: "#7c3aed" }} /> Forecast</span>
            <span className="leg"><i className="area" style={{ background: "rgba(124,58,237,.3)" }} /> 95% Interval</span>
          </div>
        }
        style={{ marginBottom: "var(--gap)" }}
      >
        <EChart build={buildForecastChart(horizon)} deps={[horizon]} themeKey={horizon} height={324} />
      </Card>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0,1.3fr) minmax(0,1fr)", marginBottom: "var(--gap)" }}>
        <Card title="Forecast Detail" icon="table" sub={`${rows.length}-day projection with confidence bounds`} actions={<span className="tag-cap">{horizon === "day" ? "Next Day" : horizon === "week" ? "Next 7 Days" : "Next 30 Days"}</span>} noBody>
          <div style={{ maxHeight: 320, overflowY: "auto" }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Date</th>
                  <th style={{ textAlign: "right" }}>Forecast (kWh)</th>
                  <th style={{ textAlign: "right" }}>Lower Bound</th>
                  <th style={{ textAlign: "right" }}>Upper Bound</th>
                  <th style={{ textAlign: "right" }}>Interval</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.t}>
                    <td className="t-strong">{new Date(row.t).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}</td>
                    <td className="mono" style={{ textAlign: "right", fontWeight: 600 }}>{fmt(row.yhat)}</td>
                    <td className="mono" style={{ textAlign: "right", color: "var(--muted)" }}>{fmt(row.lower)}</td>
                    <td className="mono" style={{ textAlign: "right", color: "var(--muted)" }}>{fmt(row.upper)}</td>
                    <td className="mono" style={{ textAlign: "right", color: "var(--muted-2)", fontSize: 11.5 }}>+/-{fmt((row.upper - row.lower) / 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Model Performance" icon="cpu" iconTone="violet" sub="Accuracy metrics - last 14 evaluation windows">
          <div className="grid" style={{ gap: 12 }}>
            {MODEL_PERF.map((metric) => <ModelPerfCard key={metric.key} m={metric} />)}
          </div>
        </Card>
      </div>

      <Card title="Export & Reports" icon="download" sub="Download forecast data and model reports for stakeholders">
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <button className="btn" onClick={() => showToast("Exporting forecast.csv...")}><Icon name="doc" /> Export CSV</button>
          <button className="btn" onClick={() => showToast("Exporting forecast.xlsx...")}><Icon name="excel" /> Export Excel</button>
          <button className="btn btn-primary" onClick={() => showToast("Generating Forecast Report (PDF)...")}><Icon name="download" /> Download Forecast Report</button>
          <div className="divider" style={{ margin: "0 4px" }} />
          <div style={{ fontSize: 11.5, color: "var(--muted)", display: "flex", alignItems: "center", gap: 7 }}>
            <Icon name="cpu" style={{ width: 14, height: 14 }} /> Model <b className="mono" style={{ color: "var(--ink-2)" }}>v2.4.1</b> - TFT - last retrained 2 days ago
          </div>
        </div>
      </Card>

      {toast && (
        <div style={{ position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)", background: "var(--ink)", color: "var(--surface)", padding: "11px 18px", borderRadius: 10, fontSize: 13, fontWeight: 550, boxShadow: "var(--shadow-lg)", zIndex: 60, display: "flex", alignItems: "center", gap: 9 }}>
          <Spinner size={14} /> {toast}
        </div>
      )}
    </div>
  );
}
