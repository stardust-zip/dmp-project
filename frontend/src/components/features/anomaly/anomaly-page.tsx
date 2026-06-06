"use client";

import { useMemo, useState } from "react";
import { buildAnomalyTimeline, EChart } from "@/components/common/charts";
import { Icon } from "@/components/common/icons";
import { Card, Field, Select, SeverityBadge, StatusBadge, toneStyle } from "@/components/common/primitives";
import { AlertDrawer } from "@/components/features/anomaly/alert-drawer";
import { ALERTS_ALL, ALERT_TYPES, ANOMALY_SUMMARY, BUILDINGS, SITES } from "@/lib/mock-data";
import { clock, fmt } from "@/lib/format";
import type { Alert } from "@/types";

type SortKey = "ts" | "building" | "actual" | "expected" | "dev" | "sev";
type Filters = {
  site: string;
  building: string;
  range: string;
  severity: string;
  type: string;
};

function AnomalySummaryCard({ c }: { c: (typeof ANOMALY_SUMMARY)[number] }) {
  const positive = c.delta > 0;
  return (
    <div className="kpi">
      <div className="kpi-top">
        <span className="kpi-label">{c.label}</span>
        <span className="kpi-ic" style={toneStyle(c.tone)}>
          <Icon name={c.icon} />
        </span>
      </div>
      <div className="kpi-val" style={{ fontSize: "calc(var(--kpi-val) + 1px)" }}>{c.value}</div>
      <div className="kpi-foot">
        <span className={`delta ${positive ? "up" : "down"}`}>
          <Icon name={positive ? "arrowUp" : "arrowDown"} style={{ width: 12, height: 12 }} />
          {positive ? "+" : ""}{c.delta}
        </span>
        <span style={{ color: "var(--muted-2)" }}>.</span>
        <span>{c.sub}</span>
      </div>
    </div>
  );
}

export function AnomalyPage() {
  const [filters, setFilters] = useState<Filters>({ site: "all", building: "all", range: "7d", severity: "all", type: "all" });
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "ts", dir: "desc" });
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Alert | null>(null);
  const perPage = 8;

  const set = (key: keyof Filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  };

  const buildingOptions = useMemo(() => {
    const list = filters.site === "all" ? BUILDINGS : BUILDINGS.filter((building) => building.site === filters.site);
    return [{ value: "all", label: "All Buildings" }, ...list.map((building) => ({ value: building.id, label: building.name }))];
  }, [filters.site]);

  const filtered = useMemo(() => {
    const rows = ALERTS_ALL.filter((alert) => {
      if (filters.site !== "all" && alert.building.site !== filters.site) return false;
      if (filters.building !== "all" && alert.building.id !== filters.building) return false;
      if (filters.severity !== "all" && alert.sev !== filters.severity) return false;
      if (filters.type !== "all" && alert.type !== filters.type) return false;
      if (search) {
        const query = search.toLowerCase();
        return (
          alert.id.toLowerCase().includes(query) ||
          alert.building.name.toLowerCase().includes(query) ||
          alert.meter.toLowerCase().includes(query) ||
          alert.type.toLowerCase().includes(query)
        );
      }
      return true;
    });
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const severityRank = { critical: 3, warning: 2, info: 1 };
      const values = {
        ts: [a.ts, b.ts],
        building: [a.building.name, b.building.name],
        actual: [a.actual ?? 0, b.actual ?? 0],
        expected: [a.expected ?? 0, b.expected ?? 0],
        dev: [a.dev ?? 0, b.dev ?? 0],
        sev: [severityRank[a.sev], severityRank[b.sev]],
      }[sort.key];
      const [x, y] = values;
      if (x < y) return -1 * dir;
      if (x > y) return 1 * dir;
      return 0;
    });
  }, [filters, search, sort]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / perPage));
  const pageRows = filtered.slice((page - 1) * perPage, page * perPage);

  const toggleSort = (key: SortKey) => {
    setSort((current) => (current.key === key ? { key, dir: current.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }));
  };

  const SortTh = ({ k, children, right }: { k: SortKey; children: React.ReactNode; right?: boolean }) => (
    <th className="sortable" onClick={() => toggleSort(k)} style={right ? { textAlign: "right" } : undefined}>
      <span className="th-in" style={right ? { flexDirection: "row-reverse" } : undefined}>
        {children}
        {sort.key === k && <Icon name={sort.dir === "asc" ? "arrowUp" : "arrowDown"} className="sort-ind" style={{ width: 12, height: 12 }} />}
      </span>
    </th>
  );

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Anomaly Detection</h1>
          <p className="page-sub">Investigate abnormal electricity consumption behavior</p>
        </div>
        <div className="page-head-actions">
          <button className="btn"><Icon name="download" /> Export</button>
          <button className="btn btn-primary"><Icon name="flag" /> Create Rule</button>
        </div>
      </div>

      <Card
        icon="filter"
        title="Filters"
        sub={`${filtered.length} of ${ALERTS_ALL.length} alerts match`}
        actions={
          <button
            className="btn btn-sm btn-ghost"
            onClick={() => {
              setFilters({ site: "all", building: "all", range: "7d", severity: "all", type: "all" });
              setSearch("");
              setPage(1);
            }}
          >
            <Icon name="refresh" /> Reset
          </button>
        }
        style={{ marginBottom: "var(--gap)" }}
      >
        <div className="grid" style={{ gridTemplateColumns: "repeat(5, minmax(0,1fr))", gap: 12 }}>
          <Field label="Site">
            <Select value={filters.site} onChange={(value) => { set("site", value); set("building", "all"); }} options={[{ value: "all", label: "All Sites" }, ...SITES.map((site) => ({ value: site, label: site }))]} />
          </Field>
          <Field label="Building">
            <Select value={filters.building} onChange={(value) => set("building", value)} options={buildingOptions} />
          </Field>
          <Field label="Date Range">
            <Select value={filters.range} onChange={(value) => set("range", value)} options={[{ value: "24h", label: "Last 24 Hours" }, { value: "7d", label: "Last 7 Days" }, { value: "30d", label: "Last 30 Days" }, { value: "90d", label: "Last 90 Days" }]} />
          </Field>
          <Field label="Severity">
            <Select value={filters.severity} onChange={(value) => set("severity", value)} options={[{ value: "all", label: "All Severities" }, { value: "critical", label: "Critical" }, { value: "warning", label: "Warning" }, { value: "info", label: "Info" }]} />
          </Field>
          <Field label="Alert Type">
            <Select value={filters.type} onChange={(value) => set("type", value)} options={[{ value: "all", label: "All Types" }, ...ALERT_TYPES.map((type) => ({ value: type, label: type }))]} />
          </Field>
        </div>
      </Card>

      <Card
        title="Anomaly Timeline"
        icon="pulse"
        iconTone="red"
        sub="Actual consumption vs. expected baseline - anomalies marked in red"
        actions={
          <div className="legend">
            <span className="leg" style={{ color: "var(--accent-600)" }}><i style={{ background: "var(--accent-600)" }} /> Actual</span>
            <span className="leg"><i className="dash" style={{ color: "var(--muted)" }} /> Expected Baseline</span>
            <span className="leg" style={{ color: "var(--red)" }}><i style={{ background: "var(--red)", width: 8, height: 8, borderRadius: "50%" }} /> Anomaly</span>
          </div>
        }
        style={{ marginBottom: "var(--gap)" }}
      >
        <EChart build={buildAnomalyTimeline()} deps={[]} themeKey="anomaly" height={320} />
      </Card>

      <div className="grid" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))", marginBottom: "var(--gap)" }}>
        {ANOMALY_SUMMARY.map((summary) => <AnomalySummaryCard key={summary.key} c={summary} />)}
      </div>

      <Card
        title="Alert Log"
        icon="table"
        sub="Click any row to investigate"
        actions={
          <div className="search" style={{ width: 220 }}>
            <Icon name="search" />
            <input placeholder="Search alerts, meters, buildings..." value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} />
          </div>
        }
        noBody
      >
        <div style={{ overflowX: "auto" }}>
          <table className="tbl tbl-clickable" style={{ minWidth: 920 }}>
            <thead>
              <tr>
                <SortTh k="ts">Timestamp</SortTh>
                <SortTh k="building">Building</SortTh>
                <th>Meter ID</th>
                <SortTh k="actual" right>Actual</SortTh>
                <SortTh k="expected" right>Expected</SortTh>
                <SortTh k="dev" right>Deviation</SortTh>
                <th>Anomaly Type</th>
                <SortTh k="sev">Severity</SortTh>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {pageRows.length === 0 && (
                <tr>
                  <td colSpan={9}><div className="empty">No alerts match your filters.</div></td>
                </tr>
              )}
              {pageRows.map((alert) => (
                <tr key={alert.id} className={selected?.id === alert.id ? "sel" : ""} onClick={() => setSelected(alert)}>
                  <td className="mono" style={{ color: "var(--muted)" }}>{clock(alert.ts)}</td>
                  <td className="t-strong">{alert.building.name}</td>
                  <td className="mono meter-id">{alert.meter}</td>
                  <td className="mono" style={{ textAlign: "right" }}>{alert.actual != null ? fmt(alert.actual) : "-"}</td>
                  <td className="mono" style={{ textAlign: "right", color: "var(--muted)" }}>{alert.expected != null ? fmt(alert.expected) : "-"}</td>
                  <td className="mono" style={{ textAlign: "right" }}>
                    {alert.dev == null ? <span className="muted">-</span> : <span className={alert.dev > 0 ? "dev-pos" : "dev-neg"}>{alert.dev > 0 ? "+" : ""}{alert.dev.toFixed(1)}%</span>}
                  </td>
                  <td>{alert.type}</td>
                  <td><SeverityBadge sev={alert.sev} /></td>
                  <td><StatusBadge status={alert.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="pager">
          <span>
            Showing <b style={{ color: "var(--ink-2)" }}>{filtered.length === 0 ? 0 : (page - 1) * perPage + 1}-{Math.min(page * perPage, filtered.length)}</b> of <b style={{ color: "var(--ink-2)" }}>{filtered.length}</b>
          </span>
          <div className="pager-btns">
            <button className="pg" disabled={page === 1} onClick={() => setPage(1)}>{"<<"}</button>
            <button className="pg" disabled={page === 1} onClick={() => setPage((current) => current - 1)}><Icon name="chevLeft" style={{ width: 13, height: 13 }} /></button>
            {Array.from({ length: Math.min(totalPages, 7) }).map((_, index) => {
              const pageNumber = index + 1;
              return <button key={pageNumber} className={`pg${pageNumber === page ? " on" : ""}`} onClick={() => setPage(pageNumber)}>{pageNumber}</button>;
            })}
            <button className="pg" disabled={page === totalPages} onClick={() => setPage((current) => current + 1)}><Icon name="chevRight" style={{ width: 13, height: 13 }} /></button>
            <button className="pg" disabled={page === totalPages} onClick={() => setPage(totalPages)}>{">>"}</button>
          </div>
        </div>
      </Card>

      {selected && <AlertDrawer alert={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
