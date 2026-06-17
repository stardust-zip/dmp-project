"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { buildByBuilding, buildTrend, EChart } from "@/components/common/charts";
import { Icon } from "@/components/common/icons";
import { Card, KpiCard } from "@/components/common/primitives";
import { AlertDrawer } from "@/components/features/anomaly/alert-drawer";
import { ALERTS_RECENT, BUILDINGS, HEALTH, KPIS, SITES } from "@/lib/mock-data";
import { fmt, timeAgo } from "@/lib/format";
import type { Alert } from "@/types";

export function DashboardPage() {
  const [range, setRange] = useState<"24h" | "7d" | "30d">("24h");
  const [area, setArea] = useState(true);
  const [alert, setAlert] = useState<Alert | null>(null);
  const [openKpi, setOpenKpi] = useState<string | null>(null);
  const themeKey = useMemo(() => `dashboard-${range}-${area}`, [range, area]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Operations Dashboard</h1>
          <p className="page-sub">
            Real-time energy consumption and system health across {SITES.length} sites and {BUILDINGS.length} buildings
          </p>
        </div>
        <div className="page-head-actions">
          <button className="btn btn-primary">
            <Icon name="download" /> Export
          </button>
        </div>
      </div>

      <div className="grid kpi-summary">
        {KPIS.map((kpi, index) => (
          <KpiCard
            key={kpi.key}
            kpi={kpi}
            open={openKpi === kpi.key}
            onToggle={() => setOpenKpi((current) => (current === kpi.key ? null : kpi.key))}
            onClose={() => setOpenKpi(null)}
            windowAlign={index >= KPIS.length - 2 ? "end" : "start"}
          />
        ))}
      </div>

      <div className="grid dashboard-chart-grid" style={{ marginBottom: "var(--gap)" }}>
        <Card
          title="Energy Consumption Trend"
          icon="pulse"
          sub="Actual vs. forecast consumption"
          actions={
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <div className="seg">
                {[
                  { value: "24h", label: "24 Hours" },
                  { value: "7d", label: "7 Days" },
                  { value: "30d", label: "30 Days" },
                ].map((option) => (
                  <button key={option.value} className={range === option.value ? "on" : ""} onClick={() => setRange(option.value as typeof range)}>
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          }
        >
          <div className="legend" style={{ marginBottom: 10 }}>
            <span className="leg" style={{ color: "var(--accent-600)" }}>
              <i style={{ background: "var(--accent-600)" }} /> Actual Consumption
            </span>
            <span className="leg">
              <i className="dash" style={{ color: "var(--muted)" }} /> Expected Baseline
            </span>
            <span className="leg" style={{ color: "#7c3aed" }}>
              <i className="dash" style={{ color: "#7c3aed" }} /> Forecast
            </span>
            <button className="btn btn-sm btn-ghost" style={{ marginLeft: "auto" }} onClick={() => setArea((value) => !value)}>
              <Icon name={area ? "eye" : "pulse"} /> {area ? "Area" : "Line"}
            </button>
          </div>
          <EChart build={buildTrend(range, area)} deps={[range, area]} themeKey={themeKey} height={296} />
        </Card>

        <Card title="Consumption by Building" icon="building" sub="Top consumers today (kWh)" actions={<span className="tag-cap">Today</span>}>
          <EChart build={buildByBuilding()} deps={[]} themeKey={themeKey} height={296} />
        </Card>
      </div>

      <div className="grid dashboard-lower-grid">
        <Card
          title="Recent Alerts"
          icon="bell"
          iconTone="orange"
          sub="Latest anomaly notifications"
          actions={
            <Link className="btn btn-sm" href="/anomaly">
              View all <Icon name="arrowRight" />
            </Link>
          }
          noBody
        >
          <div className="table-scroll">
            <table className="tbl tbl-clickable">
            <thead>
              <tr>
                <th>Time</th>
                <th>Building</th>
                <th>Alert Type</th>
                <th>Severity</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {ALERTS_RECENT.map((row) => (
                <tr key={row.id} onClick={() => setAlert(row)}>
                  <td className="mono" style={{ color: "var(--muted)" }}>{timeAgo(row.ts)}</td>
                  <td className="t-strong">{row.building.name}</td>
                  <td>{row.type}</td>
                  <td><span className={`badge badge-${row.sev}`}><i className="bdot" />{row.sev}</span></td>
                  <td><span className="badge badge-open"><i className="bdot" />{row.status}</span></td>
                </tr>
              ))}
            </tbody>
            </table>
          </div>
        </Card>

        <Card
          title="Building Health Overview"
          icon="shield"
          iconTone="green"
          sub="Status across monitored buildings"
          actions={
            <div style={{ display: "flex", gap: 10, fontSize: 11, color: "var(--muted)" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}><i className="status-dot s-green" /> Normal</span>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}><i className="status-dot s-yellow" /> Warning</span>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}><i className="status-dot s-red" /> Critical</span>
            </div>
          }
        >
          <div className="grid health-grid" style={{ gap: 10 }}>
            {HEALTH.slice(0, 8).map((building) => {
              const statusClass = building.status === "red" ? "s-red" : building.status === "yellow" ? "s-yellow" : "s-green";
              const barColor = building.status === "red" ? "var(--red)" : building.status === "yellow" ? "var(--amber)" : "var(--green)";
              return (
                <div className="health-card" key={building.id}>
                  <span className="hc-bar" style={{ background: barColor }} />
                  <div className="hc-top">
                    <div>
                      <div className="hc-name">{building.name}</div>
                      <div className="hc-meta">{building.site} - {building.note}</div>
                    </div>
                    <i className={`status-dot ${statusClass}`} />
                  </div>
                  <div className="hc-val">{fmt(building.consumption)} <small>kWh</small></div>
                  <div className="bar" style={{ marginTop: 8 }}>
                    <i style={{ width: `${Math.round(building.load * 100)}%`, background: barColor }} />
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      {alert && <AlertDrawer alert={alert} onClose={() => setAlert(null)} />}
    </div>
  );
}
