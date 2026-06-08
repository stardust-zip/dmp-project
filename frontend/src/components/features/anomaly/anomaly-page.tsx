"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { buildUnifiedAnomalyTimeline, EChart } from "@/components/common/charts";
import { Icon } from "@/components/common/icons";
import { AnomalySeverityBadge, Card, Field, Select, Spinner, toneStyle } from "@/components/common/primitives";
import { AnomalyEventDrawer } from "@/components/features/anomaly/anomaly-event-drawer";
import { getAnomalyEvents, getAnomalyFacets, getAnomalyOverview, getAnomalyTimeline, type AnomalyQuery } from "@/lib/anomaly-api";
import { clock, fmt, fmt1 } from "@/lib/format";
import type { AnomalyEvent, AnomalyEventsResponse, AnomalyFacets, AnomalyOverview, AnomalySeverity, Tone } from "@/types";

type DateRange = "all" | "2017" | "2016" | "scored";
type SortKey = "severity" | "newest" | "oldest" | "duration";

type Filters = {
  site: string;
  building: string;
  severity: string;
  type: string;
  range: DateRange;
  sort: SortKey;
};

const PER_PAGE = 25;

const EMPTY_OVERVIEW: AnomalyOverview = {
  total_anomalies: 0,
  critical_anomalies: 0,
  buildings_affected: 0,
  most_affected_site: null,
  time_min: null,
  time_max: null,
  severity_counts: { Critical: 0, High: 0, Medium: 0, Low: 0 },
  type_counts: {},
};

function rangeQuery(range: DateRange) {
  if (range === "scored") return { start: "2017-10-01T00:00:00", end: "2017-12-31T23:00:00" };
  if (range === "2017") return { start: "2017-01-01T00:00:00", end: "2017-12-31T23:00:00" };
  if (range === "2016") return { start: "2016-01-01T00:00:00", end: "2016-12-31T23:00:00" };
  return {};
}

function eventTime(event: AnomalyEvent) {
  return clock(new Date(event.start_time).getTime());
}

function valueCell(value?: number | null) {
  return value == null ? <span className="muted">-</span> : <span>{fmt(value)}</span>;
}

function durationLabel(hours?: number | null) {
  if (hours == null) return "-";
  if (hours < 24) return `${fmt1(hours)}h`;
  const days = Math.floor(hours / 24);
  const rest = Math.round(hours % 24);
  return rest ? `${days}d ${rest}h` : `${days}d`;
}

function severityTone(severity: AnomalySeverity): Tone {
  if (severity === "Critical") return "red";
  if (severity === "High") return "orange";
  if (severity === "Medium") return "amber";
  return "accent";
}

function queryFrom(filters: Filters, page: number): AnomalyQuery {
  return {
    site: filters.site,
    building: filters.building,
    severity: filters.severity,
    type: filters.type,
    sort: filters.sort,
    limit: PER_PAGE,
    offset: (page - 1) * PER_PAGE,
    ...rangeQuery(filters.range),
  };
}

function SeverityMeter({ overview }: { overview: AnomalyOverview }) {
  const entries: Array<{ severity: AnomalySeverity; label: string }> = [
    { severity: "Critical", label: "Critical" },
    { severity: "High", label: "High" },
    { severity: "Medium", label: "Medium" },
    { severity: "Low", label: "Low" },
  ];
  const max = Math.max(1, ...entries.map(({ severity }) => overview.severity_counts[severity] ?? 0));

  return (
    <div className="severity-stack">
      {entries.map(({ severity, label }) => {
        const count = overview.severity_counts[severity] ?? 0;
        return (
          <div className="severity-line" key={severity}>
            <div className="severity-line-top">
              <span>{label}</span>
              <b className="mono">{fmt(count)}</b>
            </div>
            <div className="severity-track">
              <i style={{ width: `${Math.max(4, (count / max) * 100)}%`, background: `var(--anom-${severity.toLowerCase()})` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function AttentionQueue({ events, onSelect }: { events: AnomalyEvent[]; onSelect: (event: AnomalyEvent) => void }) {
  const rows = events.slice(0, 6);
  return (
    <div className="attention-list">
      {rows.length === 0 && <div className="empty" style={{ padding: 18 }}>No urgent events in this filter.</div>}
      {rows.map((event) => (
        <button className="attention-row" key={event.id} type="button" onClick={() => onSelect(event)}>
          <span className="attention-dot" style={{ background: `var(--anom-${event.severity.toLowerCase()})` }} />
          <span className="attention-main">
            <b>{event.building_id}</b>
            <span>{event.type}</span>
          </span>
          <span className="attention-meta mono">{durationLabel(event.duration_hours)}</span>
        </button>
      ))}
    </div>
  );
}

function SelectionGate({ siteSelected }: { siteSelected: boolean }) {
  return (
    <div className="anomaly-gate">
      <div className="anomaly-gate-inner">
        <div className="anomaly-gate-icon">
          <Icon name="building" />
        </div>
        <h2 className="anomaly-gate-title">Select a building to begin</h2>
        <p className="anomaly-gate-desc">
          {siteSelected
            ? "Choose a building from the dropdown above to load its anomaly timeline, event log, and severity distribution."
            : "Start by selecting a site, then choose a specific building to analyze its anomaly history."}
        </p>
      </div>
    </div>
  );
}

export function AnomalyPage() {
  const [filters, setFilters] = useState<Filters>({ site: "all", building: "all", severity: "all", type: "all", range: "scored", sort: "severity" });
  const [page, setPage] = useState(1);
  const [facets, setFacets] = useState<AnomalyFacets>({ sites: [], buildings: [], severities: ["Critical", "High", "Medium", "Low"], types: [] });
  const [filteredBuildings, setFilteredBuildings] = useState<string[]>([]);
  const allBuildingsRef = useRef<string[]>([]);
  const buildingsBySiteRef = useRef<Record<string, string[]>>({});
  const [overview, setOverview] = useState<AnomalyOverview>(EMPTY_OVERVIEW);
  const [events, setEvents] = useState<AnomalyEventsResponse>({ total: 0, limit: PER_PAGE, offset: 0, items: [] });
  const [timeline, setTimeline] = useState<AnomalyEvent[]>([]);
  const [selected, setSelected] = useState<AnomalyEvent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const query = useMemo(() => queryFrom(filters, page), [filters, page]);
  const chartQuery = useMemo<AnomalyQuery>(() => ({ ...queryFrom(filters, 1), limit: 1500, offset: 0, sort: "newest" }), [filters]);

  const isGated = filters.building === "all";

  // Load all facets on mount
  useEffect(() => {
    const controller = new AbortController();
    getAnomalyFacets(undefined, controller.signal)
      .then((data) => {
        setFacets(data);
        allBuildingsRef.current = data.buildings;
        setFilteredBuildings(data.buildings);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, []);

  // Derive buildings for the selected site from the timeline endpoint,
  // which does respect site_id filtering (unlike the flat facets list).
  useEffect(() => {
    if (filters.site === "all") {
      setFilteredBuildings(allBuildingsRef.current);
      return;
    }
    // Serve from cache if we already fetched this site
    if (buildingsBySiteRef.current[filters.site]) {
      setFilteredBuildings(buildingsBySiteRef.current[filters.site]);
      return;
    }
    const controller = new AbortController();
    getAnomalyTimeline({ site: filters.site, limit: 1500 }, controller.signal)
      .then((data) => {
        const buildings = [...new Set(data.items.map((e) => e.building_id))].sort();
        buildingsBySiteRef.current[filters.site] = buildings;
        setFilteredBuildings(buildings);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") console.error(err);
      });
    return () => controller.abort();
  }, [filters.site]);

  // Fetch event data only once a specific building is chosen
  useEffect(() => {
    if (query.building === "all") {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError(null);
    Promise.all([
      getAnomalyOverview(query, controller.signal),
      getAnomalyEvents(query, controller.signal),
      getAnomalyTimeline(chartQuery, controller.signal),
    ])
      .then(([nextOverview, nextEvents, nextTimeline]) => {
        setOverview(nextOverview);
        setEvents(nextEvents);
        setTimeline(nextTimeline.items);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => setLoading(false));

    return () => controller.abort();
  }, [chartQuery, query]);

  const set = (key: keyof Filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  };

  const totalPages = Math.max(1, Math.ceil(events.total / PER_PAGE));
  const typeEntries = Object.entries(overview.type_counts).slice(0, 6);

  const buildingOptions = filters.site === "all"
    ? [{ value: "all" as const, label: "Select a site first" }]
    : [{ value: "all" as const, label: "All Buildings" }, ...filteredBuildings.map((b) => ({ value: b, label: b }))];

  return (
    <div className="page anomaly-page">
      <div className="page-head anomaly-head">
        <div>
          <h1 className="page-title">Anomaly Detection</h1>
          <p className="page-sub">Building-level triage by site, hour, severity, and event type</p>
        </div>
      </div>

      <Card
        icon="filter"
        title="Filters"
        sub={isGated ? "Select a site and building to begin" : `${fmt(events.total)} anomalies match`}
        actions={
          <button
            className="btn btn-sm btn-ghost"
            onClick={() => {
              setFilters({ site: "all", building: "all", severity: "all", type: "all", range: "scored", sort: "severity" });
              setPage(1);
            }}
          >
            <Icon name="refresh" /> Reset
          </button>
        }
        style={{ marginBottom: "var(--gap)" }}
      >
        <div className="grid anomaly-filter-grid">
          <Field label="Site">
            <Select
              value={filters.site}
              onChange={(value) => {
                set("site", value);
                set("building", "all");
              }}
              options={[{ value: "all", label: "All Sites" }, ...facets.sites.map((site) => ({ value: site, label: site }))]}
            />
          </Field>
          <Field label="Building">
            <Select
              value={filters.building}
              onChange={(value) => set("building", value)}
              disabled={filters.site === "all"}
              options={buildingOptions}
            />
          </Field>
          <Field label="Severity">
            <Select value={filters.severity} onChange={(value) => set("severity", value)} options={[{ value: "all", label: "All Severities" }, ...facets.severities.map((severity) => ({ value: severity, label: severity }))]} />
          </Field>
          <Field label="Type">
            <Select value={filters.type} onChange={(value) => set("type", value)} options={[{ value: "all", label: "All Types" }, ...facets.types.map((type) => ({ value: type, label: type }))]} />
          </Field>
          <Field label="Date Range">
            <Select value={filters.range} onChange={(value) => set("range", value)} options={[{ value: "scored", label: "Oct-Dec 2017" }, { value: "2017", label: "2017" }, { value: "2016", label: "2016" }, { value: "all", label: "All Dates" }]} />
          </Field>
          <Field label="Sort">
            <Select value={filters.sort} onChange={(value) => set("sort", value)} options={[{ value: "severity", label: "Severity First" }, { value: "newest", label: "Newest First" }, { value: "oldest", label: "Oldest First" }, { value: "duration", label: "Longest First" }]} />
          </Field>
        </div>
      </Card>

      {error && (
        <div className="empty anomaly-error">
          Could not load anomaly results. Confirm the backend is running and the notebook exports exist.
          <div className="mono" style={{ marginTop: 6 }}>{error}</div>
        </div>
      )}

      {isGated ? (
        <SelectionGate siteSelected={filters.site !== "all"} />
      ) : (
        <div className="grid anomaly-main-grid">
          <div className="anomaly-workspace">
            <Card
              title="Timeline"
              icon="pulse"
              iconTone="red"
              sub="Each marker is one anomaly. Larger markers lasted longer."
              actions={
                <div className="legend">
                  {(["Critical", "High", "Medium", "Low"] as AnomalySeverity[]).map((severity) => (
                    <span className="leg" key={severity}>
                      <i style={{ background: `var(--anom-${severity.toLowerCase()})`, width: 8, height: 8, borderRadius: "50%" }} />
                      {severity}
                    </span>
                  ))}
                </div>
              }
            >
              {loading ? <div className="empty"><Spinner /> Loading timeline...</div> : <EChart build={buildUnifiedAnomalyTimeline(timeline)} deps={[timeline]} themeKey="unified-anomaly" height={312} />}
            </Card>

            <Card
              title="Event Log"
              icon="table"
              sub="Click any row to inspect the event"
              noBody
              actions={loading ? <span className="muted row" style={{ gap: 6 }}><Spinner /> Loading</span> : undefined}
            >
              <div className="anomaly-table-scroll">
                <table className="tbl tbl-clickable anomaly-event-table" style={{ minWidth: 1080 }}>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Site</th>
                      <th>Building</th>
                      <th>Type</th>
                      <th>Severity</th>
                      <th style={{ textAlign: "right" }}>Actual</th>
                      <th style={{ textAlign: "right" }}>Expected</th>
                      <th style={{ textAlign: "right" }}>Duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!loading && events.items.length === 0 && (
                      <tr>
                        <td colSpan={8}><div className="empty">No anomalies match your filters.</div></td>
                      </tr>
                    )}
                    {events.items.map((event) => (
                      <tr key={event.id} className={selected?.id === event.id ? "sel" : ""} onClick={() => setSelected(event)}>
                        <td className="mono" style={{ color: "var(--muted)" }}>{eventTime(event)}</td>
                        <td>{event.site_id}</td>
                        <td className="t-strong">{event.building_id}</td>
                        <td>
                          <span className="type-chip" style={toneStyle(severityTone(event.severity))}>
                            {event.type}
                          </span>
                        </td>
                        <td><AnomalySeverityBadge severity={event.severity} /></td>
                        <td className="mono" style={{ textAlign: "right" }}>{valueCell(event.actual_value)}</td>
                        <td className="mono" style={{ textAlign: "right" }}>{valueCell(event.expected_value)}</td>
                        <td className="mono" style={{ textAlign: "right" }}>{durationLabel(event.duration_hours)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="pager">
                <span>
                  Showing <b style={{ color: "var(--ink-2)" }}>{events.total === 0 ? 0 : events.offset + 1}-{Math.min(events.offset + events.limit, events.total)}</b> of <b style={{ color: "var(--ink-2)" }}>{fmt(events.total)}</b>
                </span>
                <div className="pager-btns">
                  <button className="pg" disabled={page === 1} onClick={() => setPage(1)}>{"<<"}</button>
                  <button className="pg" disabled={page === 1} onClick={() => setPage((current) => Math.max(1, current - 1))}><Icon name="chevLeft" style={{ width: 13, height: 13 }} /></button>
                  <button className="pg on">{page}</button>
                  <button className="pg" disabled={page === totalPages} onClick={() => setPage((current) => Math.min(totalPages, current + 1))}><Icon name="chevRight" style={{ width: 13, height: 13 }} /></button>
                  <button className="pg" disabled={page === totalPages} onClick={() => setPage(totalPages)}>{">>"}</button>
                </div>
              </div>
            </Card>
          </div>

          <aside className="anomaly-rail">
            <Card title="Severity" icon="alert" iconTone="red" sub="Distribution in view">
              <SeverityMeter overview={overview} />
            </Card>

            <Card title="Attention Queue" icon="flag" iconTone="orange" sub="Highest priority rows">
              <AttentionQueue events={events.items} onSelect={setSelected} />
            </Card>

            <Card title="Type Profile" icon="layers" sub="Most common event classes">
              <div className="anomaly-type-list">
                {typeEntries.length === 0 && <div className="empty" style={{ padding: 18 }}>No anomaly types match.</div>}
                {typeEntries.map(([type, count]) => {
                  const ratio = overview.total_anomalies ? Math.max(4, (count / overview.total_anomalies) * 100) : 0;
                  return (
                    <div className="type-row" key={type}>
                      <div>
                        <b>{type}</b>
                        <span className="mono">{fmt(count)}</span>
                      </div>
                      <div className="bar"><i style={{ width: `${ratio}%`, background: "var(--accent-600)" }} /></div>
                    </div>
                  );
                })}
              </div>
            </Card>
          </aside>
        </div>
      )}

      {selected && <AnomalyEventDrawer event={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
