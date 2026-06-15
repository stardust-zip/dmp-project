"use client";

import { useEffect, useMemo, useState } from "react";
import { buildUnifiedAnomalyTimeline, EChart } from "@/components/common/charts";
import { Icon } from "@/components/common/icons";
import { AnomalySeverityBadge, Card, Field, Select, Spinner, toneStyle } from "@/components/common/primitives";
import { AlertFeed } from "@/components/features/anomaly/anomaly-alert-feed";
import { AnomalyEventDrawer } from "@/components/features/anomaly/anomaly-event-drawer";
import { useAlerts } from "@/hooks/use-alerts";
import { getAnomalyFacets, getAnomalyTimeline, type AnomalyQuery } from "@/lib/anomaly-api";
import { clock, displayLocationName, fmt, fmtKwh } from "@/lib/format";
import type { AnomalyEvent, AnomalyEventsResponse, AnomalyFacets, AnomalyOverview, AnomalySeverity, AnomalyTimelineGap, AnomalyTimelineResponse, Tone } from "@/types";

type DateRange = "all" | "2017" | "2016" | "scored";
type SortKey = "severity" | "newest" | "oldest";
type SpeedOption = "1" | "6" | "24";
type SimBounds = { start: number; end: number };
type PendingOpen = "primaryUsage" | "building" | null;

type Filters = {
  site: string;
  building: string;
  primaryUsage: string;
  severity: string;
  type: string;
  range: DateRange;
  sort: SortKey;
};

const PER_PAGE = 25;
const SIMULATION_FETCH_LIMIT = 5000;
const HOUR_MS = 60 * 60 * 1000;
const MINUTE_MS = 60 * 1000;
const TICK_MS = 250;
const SPEED_OPTIONS: Array<{ value: SpeedOption; label: string }> = [
  { value: "1", label: "1h/s" },
  { value: "6", label: "6h/s" },
  { value: "24", label: "24h/s" },
];
const SEVERITY_RANK: Record<AnomalySeverity, number> = { Critical: 0, High: 1, Medium: 2, Low: 3 };

const EMPTY_TIMELINE: AnomalyTimelineResponse = { items: [], points: [], gaps: [] };

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
  return value == null ? <span className="muted">-</span> : <span>{fmtKwh(value)}</span>;
}

function severityTone(severity: AnomalySeverity): Tone {
  if (severity === "Critical") return "red";
  if (severity === "High") return "orange";
  if (severity === "Medium") return "amber";
  return "accent";
}

function buildingLabel(buildingId: string) {
  return displayLocationName(null, buildingId);
}

function timeOf(value: string) {
  return new Date(value).getTime();
}

function localTimestamp(ts: number) {
  const d = new Date(ts);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function timelineBounds(timeline: AnomalyTimelineResponse): SimBounds | null {
  const timestamps = [
    ...timeline.points.map((point) => timeOf(point.timestamp)),
    ...timeline.items.map((event) => timeOf(event.start_time)),
    ...timeline.items.flatMap((event) => (event.end_time ? [timeOf(event.end_time)] : [])),
    ...timeline.gaps.flatMap((gap) => [timeOf(gap.start_time), timeOf(gap.end_time)]),
  ].filter(Number.isFinite);

  if (timestamps.length === 0) return null;
  return { start: Math.min(...timestamps), end: Math.max(...timestamps) };
}

function clampGap(gap: AnomalyTimelineGap, simNow: number): AnomalyTimelineGap | null {
  const start = timeOf(gap.start_time);
  if (!Number.isFinite(start) || start > simNow) return null;
  const end = Math.min(timeOf(gap.end_time), simNow);
  return { ...gap, end_time: localTimestamp(end) };
}

function timelineUntil(timeline: AnomalyTimelineResponse, simNow: number): AnomalyTimelineResponse {
  return {
    points: timeline.points.filter((point) => timeOf(point.timestamp) <= simNow),
    items: timeline.items.filter((event) => timeOf(event.start_time) <= simNow),
    gaps: timeline.gaps.map((gap) => clampGap(gap, simNow)).filter((gap): gap is AnomalyTimelineGap => gap != null),
  };
}

function sortEvents(events: AnomalyEvent[], sort: SortKey) {
  return [...events].sort((a, b) => {
    if (sort === "oldest") return timeOf(a.start_time) - timeOf(b.start_time);
    if (sort === "severity") {
      const bySeverity = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity];
      if (bySeverity !== 0) return bySeverity;
    }
    return timeOf(b.start_time) - timeOf(a.start_time);
  });
}

function overviewFromEvents(events: AnomalyEvent[]): AnomalyOverview {
  const severity_counts: Record<AnomalySeverity, number> = { Critical: 0, High: 0, Medium: 0, Low: 0 };
  const type_counts: Record<string, number> = {};
  const buildings = new Set<string>();
  const siteCounts = new Map<string, number>();
  let timeMin: number | null = null;
  let timeMax: number | null = null;

  events.forEach((event) => {
    severity_counts[event.severity] += 1;
    type_counts[event.type] = (type_counts[event.type] ?? 0) + 1;
    buildings.add(event.building_id);
    siteCounts.set(event.site_id, (siteCounts.get(event.site_id) ?? 0) + 1);
    const start = timeOf(event.start_time);
    if (Number.isFinite(start)) {
      timeMin = timeMin == null ? start : Math.min(timeMin, start);
      timeMax = timeMax == null ? start : Math.max(timeMax, start);
    }
  });

  const mostAffectedSite = [...siteCounts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
  return {
    total_anomalies: events.length,
    critical_anomalies: severity_counts.Critical,
    buildings_affected: buildings.size,
    most_affected_site: mostAffectedSite,
    time_min: timeMin == null ? null : localTimestamp(timeMin),
    time_max: timeMax == null ? null : localTimestamp(timeMax),
    severity_counts,
    type_counts,
  };
}

function eventsResponseFrom(events: AnomalyEvent[], page: number): AnomalyEventsResponse {
  const offset = (page - 1) * PER_PAGE;
  return {
    total: events.length,
    limit: PER_PAGE,
    offset,
    items: events.slice(offset, offset + PER_PAGE),
  };
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

function SimulationControls({
  bounds,
  simNow,
  isPlaying,
  speed,
  disabled,
  onPlayToggle,
  onReset,
  onScrub,
  onSpeedChange,
}: {
  bounds: SimBounds | null;
  simNow: number | null;
  isPlaying: boolean;
  speed: SpeedOption;
  disabled: boolean;
  onPlayToggle: () => void;
  onReset: () => void;
  onScrub: (value: number) => void;
  onSpeedChange: (value: SpeedOption) => void;
}) {
  const canPlay = !!bounds && simNow != null && bounds.end > bounds.start && !disabled;
  const progress = bounds && simNow != null && bounds.end > bounds.start
    ? ((simNow - bounds.start) / (bounds.end - bounds.start)) * 100
    : 0;

  return (
    <div className="simulator-panel">
      <div className="simulator-controls">
        <button className="btn btn-sm btn-primary" type="button" disabled={!canPlay} onClick={onPlayToggle}>
          <Icon name={isPlaying ? "pause" : "play"} />
          {isPlaying ? "Pause" : "Play"}
        </button>
        <button className="btn btn-sm" type="button" disabled={!canPlay} onClick={onReset}>
          <Icon name="refresh" />
          Reset
        </button>
        <div className="simulator-speed">
          <Select value={speed} onChange={onSpeedChange} disabled={!canPlay} options={SPEED_OPTIONS} />
        </div>
      </div>
      <div className="simulator-readout">
        <span className="tag-cap">Simulated time</span>
        <b className="mono">{simNow == null ? "-" : clock(simNow)}</b>
        <span className="mono muted">{Math.max(0, Math.min(100, progress)).toFixed(0)}%</span>
      </div>
      <input
        className="simulator-slider"
        type="range"
        disabled={!canPlay}
        min={bounds?.start ?? 0}
        max={bounds?.end ?? 0}
        step={MINUTE_MS}
        value={simNow ?? bounds?.start ?? 0}
        onChange={(event) => onScrub(Number(event.target.value))}
        aria-label="Simulated time"
      />
    </div>
  );
}

export function AnomalyPage() {
  const [filters, setFilters] = useState<Filters>({ site: "all", building: "all", primaryUsage: "all", severity: "all", type: "all", range: "scored", sort: "severity" });
  const [page, setPage] = useState(1);
  const [facets, setFacets] = useState<AnomalyFacets>({ sites: [], buildings: [], severities: ["Critical", "High", "Medium", "Low"], types: [], primary_usage_types: [] });
  const [siteFacetsBySite, setSiteFacetsBySite] = useState<Record<string, AnomalyFacets>>({});
  const [siteEventsBySite, setSiteEventsBySite] = useState<Record<string, AnomalyEvent[]>>({});
  const [rawTimeline, setRawTimeline] = useState<AnomalyTimelineResponse>(EMPTY_TIMELINE);
  const [simBounds, setSimBounds] = useState<SimBounds | null>(null);
  const [simNow, setSimNow] = useState<number | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<SpeedOption>("6");
  const [pendingOpen, setPendingOpen] = useState<PendingOpen>(null);
  const [primaryUsageOpenSignal, setPrimaryUsageOpenSignal] = useState(0);
  const [buildingOpenSignal, setBuildingOpenSignal] = useState(0);
  const [selected, setSelected] = useState<AnomalyEvent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { statuses, acknowledge, resolve, reopen } = useAlerts();

  const replayQuery = useMemo<AnomalyQuery>(() => ({
    site: filters.site,
    building: filters.building,
    severity: filters.severity,
    type: filters.type,
    limit: SIMULATION_FETCH_LIMIT,
    ...rangeQuery(filters.range),
  }), [filters.site, filters.building, filters.severity, filters.type, filters.range]);

  const isGated = filters.building === "all";
  const visibleTimeline = useMemo(() => (simNow == null ? EMPTY_TIMELINE : timelineUntil(rawTimeline, simNow)), [rawTimeline, simNow]);
  const visibleOverview = useMemo(() => overviewFromEvents(visibleTimeline.items), [visibleTimeline.items]);
  const filteredItems = useMemo(
    () => filters.primaryUsage === "all" ? visibleTimeline.items : visibleTimeline.items.filter((e) => e.primary_space_usage === filters.primaryUsage),
    [filters.primaryUsage, visibleTimeline.items],
  );
  const sortedEvents = useMemo(() => sortEvents(filteredItems, filters.sort), [filters.sort, filteredItems]);
  const totalPages = Math.max(1, Math.ceil(sortedEvents.length / PER_PAGE));
  const safePage = Math.min(page, totalPages);
  const events = useMemo(() => eventsResponseFrom(sortedEvents, safePage), [safePage, sortedEvents]);
  const typeEntries = Object.entries(visibleOverview.type_counts).slice(0, 6);
  const visibleSelected = selected && visibleTimeline.items.some((event) => event.id === selected.id) ? selected : null;
  const openAlertCount = useMemo(
    () => visibleTimeline.items.filter((e) => (e.severity === "Critical" || e.severity === "High") && (statuses[e.id] ?? "Open") === "Open").length,
    [visibleTimeline.items, statuses],
  );
  const siteEvents = useMemo(() => (filters.site === "all" ? [] : (siteEventsBySite[filters.site] ?? [])), [filters.site, siteEventsBySite]);
  const activeFacets = filters.site === "all" ? facets : (siteFacetsBySite[filters.site] ?? facets);
  const filteredPrimaryUsages = useMemo(
    () => {
      const fromFacets = activeFacets.primary_usage_types.filter(Boolean);
      if (fromFacets.length > 0) return fromFacets;
      return [...new Set(siteEvents.map((event) => event.primary_space_usage).filter(Boolean))].sort() as string[];
    },
    [activeFacets.primary_usage_types, siteEvents],
  );
  const filteredBuildings = useMemo(() => {
    if (filters.primaryUsage === "all") return activeFacets.buildings;
    const source = siteEvents.filter((event) => event.primary_space_usage === filters.primaryUsage);
    const fromEvents = [...new Set(source.map((event) => event.building_id))].sort();
    return fromEvents.length > 0 ? fromEvents : activeFacets.buildings;
  }, [activeFacets.buildings, filters.primaryUsage, siteEvents]);

  // Load all facets on mount
  useEffect(() => {
    const controller = new AbortController();
    getAnomalyFacets(undefined, controller.signal)
      .then((data) => {
        setFacets(data);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, []);

  // Cache site-level events so primary usage and building options can be derived locally.
  useEffect(() => {
    if (filters.site === "all" || siteEventsBySite[filters.site]) return;

    const controller = new AbortController();
    getAnomalyTimeline({ site: filters.site, limit: 1500 }, controller.signal)
      .then((data) => {
        setSiteEventsBySite((current) => ({ ...current, [filters.site]: data.items }));
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") console.error(err);
      });
    return () => controller.abort();
  }, [filters.site, siteEventsBySite]);

  // Load site-scoped facets for dropdown options; this is not limited by the timeline page size.
  useEffect(() => {
    if (filters.site === "all" || siteFacetsBySite[filters.site]) return;

    const controller = new AbortController();
    getAnomalyFacets(filters.site, controller.signal)
      .then((data) => {
        setSiteFacetsBySite((current) => ({ ...current, [filters.site]: data }));
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") console.error(err);
      });
    return () => controller.abort();
  }, [filters.site, siteFacetsBySite]);

  useEffect(() => {
    if (pendingOpen !== "primaryUsage" || filters.site === "all" || filteredPrimaryUsages.length === 0) return;
    const timeout = window.setTimeout(() => {
      setPrimaryUsageOpenSignal((value) => value + 1);
      setPendingOpen(null);
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [filteredPrimaryUsages.length, filters.site, pendingOpen]);

  useEffect(() => {
    if (pendingOpen !== "building" || filters.primaryUsage === "all" || filteredBuildings.length === 0) return;
    const timeout = window.setTimeout(() => {
      setBuildingOpenSignal((value) => value + 1);
      setPendingOpen(null);
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [filteredBuildings.length, filters.primaryUsage, pendingOpen]);

  // Fetch event data only once a specific building is chosen
  useEffect(() => {
    if (replayQuery.building === "all") {
      return;
    }
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError(null);
    getAnomalyTimeline(replayQuery, controller.signal)
      .then((nextTimeline) => {
        const nextBounds = timelineBounds(nextTimeline);
        setRawTimeline(nextTimeline);
        setSimBounds(nextBounds);
        setSimNow(nextBounds?.start ?? null);
        setIsPlaying(false);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => setLoading(false));

    return () => controller.abort();
  }, [replayQuery]);

  useEffect(() => {
    if (!isPlaying || !simBounds || simBounds.end <= simBounds.start) return;
    const interval = window.setInterval(() => {
      setSimNow((current) => {
        if (current == null) return current;
        const next = Math.min(current + Number(speed) * HOUR_MS * (TICK_MS / 1000), simBounds.end);
        if (next >= simBounds.end) setIsPlaying(false);
        return next;
      });
    }, TICK_MS);

    return () => window.clearInterval(interval);
  }, [isPlaying, simBounds, speed]);

  const set = (key: keyof Filters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
    setSelected(null);
    setIsPlaying(false);
  };

  const primaryUsageOptions = filters.site === "all"
    ? []
    : [{ value: "all" as const, label: "All Usage Types" }, ...filteredPrimaryUsages.map((usage) => ({ value: usage, label: usage }))];
  const buildingOptions = filters.site === "all"
    ? []
    : [{ value: "all" as const, label: "All Buildings" }, ...filteredBuildings.map((building) => ({ value: building, label: buildingLabel(building) }))];

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
        sub={isGated ? "Select a site and building to begin" : `${fmt(events.total)} anomalies visible at simulated time`}
        actions={
          <button
            className="btn btn-sm btn-ghost"
            onClick={() => {
              setFilters({ site: "all", building: "all", primaryUsage: "all", severity: "all", type: "all", range: "scored", sort: "severity" });
              setPage(1);
              setSelected(null);
              setIsPlaying(false);
              setPendingOpen(null);
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
                set("primaryUsage", "all");
                set("building", "all");
                setPendingOpen(value === "all" ? null : "primaryUsage");
              }}
              options={[{ value: "all", label: "All Sites" }, ...facets.sites.map((site) => ({ value: site, label: site }))]}
              searchable
              searchPlaceholder="Search sites..."
            />
          </Field>
          <Field label="Primary Usage">
            <Select
              value={filters.primaryUsage}
              onChange={(value) => {
                set("primaryUsage", value);
                set("building", "all");
                setPendingOpen(value === "all" ? null : "building");
              }}
              disabled={filters.site === "all" || primaryUsageOptions.length === 0}
              options={primaryUsageOptions}
              openSignal={primaryUsageOpenSignal}
              searchable
              searchPlaceholder="Search usage..."
            />
          </Field>
          <Field label="Building">
            <Select
              value={filters.building}
              onChange={(value) => set("building", value)}
              disabled={filters.site === "all" || buildingOptions.length === 0}
              options={buildingOptions}
              openSignal={buildingOpenSignal}
              searchable
              searchPlaceholder="Search buildings..."
            />
          </Field>
          <Field label="Severity">
            <Select value={filters.severity} onChange={(value) => set("severity", value)} disabled={isGated} options={[{ value: "all", label: "All Severities" }, ...facets.severities.map((severity) => ({ value: severity, label: severity }))]} />
          </Field>
          <Field label="Type">
            <Select value={filters.type} onChange={(value) => set("type", value)} disabled={isGated} options={[{ value: "all", label: "All Types" }, ...facets.types.map((type) => ({ value: type, label: type }))]} />
          </Field>
          <Field label="Date Range">
            <Select value={filters.range} onChange={(value) => set("range", value)} disabled={isGated} options={[{ value: "scored", label: "Oct-Dec 2017" }, { value: "2017", label: "2017" }, { value: "2016", label: "2016" }, { value: "all", label: "All Dates" }]} />
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
              sub="Historical replay reveals points and anomalies up to simulated time."
              actions={
                <div className="legend">
                  {(["Critical", "High", "Medium", "Low"] as AnomalySeverity[]).map((severity) => (
                    <span className="leg" key={severity}>
                      <i style={{ background: `var(--anom-${severity.toLowerCase()})`, width: 8, height: 8, borderRadius: "50%" }} />
                      {severity}
                    </span>
                  ))}
                  <span className="leg">
                    <i style={{ background: "rgba(100,116,139,.35)", width: 8, height: 8, borderRadius: 2 }} />
                    Missing
                  </span>
                </div>
              }
            >
              <SimulationControls
                bounds={simBounds}
                simNow={simNow}
                isPlaying={isPlaying}
                speed={speed}
                disabled={loading}
                onPlayToggle={() => {
                  if (!simBounds || simNow == null) return;
                  if (simNow >= simBounds.end) setSimNow(simBounds.start);
                  setIsPlaying((current) => !current);
                }}
                onReset={() => {
                  if (!simBounds) return;
                  setSimNow(simBounds.start);
                  setIsPlaying(false);
                  setPage(1);
                  setSelected(null);
                }}
                onScrub={(value) => {
                  if (!simBounds) return;
                  setSimNow(Math.max(simBounds.start, Math.min(simBounds.end, value)));
                  setIsPlaying(false);
                  setPage(1);
                  setSelected(null);
                }}
                onSpeedChange={setSpeed}
              />
              {loading ? (
                <div className="empty"><Spinner /> Loading timeline...</div>
              ) : (
                <EChart
                  build={buildUnifiedAnomalyTimeline(visibleTimeline, {
                    cursorTime: simNow ?? undefined,
                    axisMin: simBounds?.start,
                    axisMax: simBounds?.end,
                    futurePoints: simNow == null ? [] : rawTimeline.points.filter((p) => timeOf(p.timestamp) >= simNow && timeOf(p.timestamp) <= simNow + 6 * 60 * 60 * 1000),
                  })}
                  deps={[visibleTimeline, simNow, simBounds?.start, simBounds?.end, rawTimeline.points]}
                  themeKey="unified-anomaly"
                  height={312}
                  preserveDataZoom
                />
              )}
            </Card>

            <Card
              title="Event Log"
              icon="table"
              sub="Click any row to inspect the event"
              noBody
              actions={
                loading
                  ? <span className="muted row" style={{ gap: 6}}><Spinner /> Loading</span>
                  : <div style={{ width: 148 }}><Select value={filters.sort} onChange={(value) => set("sort", value)} options={[{ value: "severity", label: "Severity First" }, { value: "newest", label: "Newest First" }, { value: "oldest", label: "Oldest First" }]} /></div>
              }
            >
              <div className="anomaly-table-scroll">
                <table className="tbl tbl-clickable anomaly-event-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Site</th>
                      <th>Building</th>
                      <th>Type</th>
                      <th>Severity</th>
                      <th style={{ textAlign: "right" }}>Actual</th>
                      <th style={{ textAlign: "right" }}>Expected</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!loading && events.items.length === 0 && (
                      <tr>
                        <td colSpan={7}><div className="empty">No anomalies match your filters.</div></td>
                      </tr>
                    )}
                    {events.items.map((event) => (
                      <tr key={event.id} className={visibleSelected?.id === event.id ? "sel" : ""} onClick={() => setSelected(event)}>
                        <td className="mono" style={{ color: "var(--muted)" }}>{eventTime(event)}</td>
                        <td>{event.site_id}</td>
                        <td className="t-strong">{buildingLabel(event.building_id)}</td>
                        <td>
                          <span className="type-chip" style={toneStyle(severityTone(event.severity))}>
                            {event.type}
                          </span>
                        </td>
                        <td><AnomalySeverityBadge severity={event.severity} /></td>
                        <td className="mono" style={{ textAlign: "right" }}>{valueCell(event.actual_value)}</td>
                        <td className="mono" style={{ textAlign: "right" }}>{valueCell(event.expected_value)}</td>
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
                  <button className="pg" disabled={safePage === 1} onClick={() => setPage(1)}>{"<<"}</button>
                  <button className="pg" disabled={safePage === 1} onClick={() => setPage((current) => Math.max(1, current - 1))}><Icon name="chevLeft" style={{ width: 13, height: 13 }} /></button>
                  <button className="pg on">{safePage}</button>
                  <button className="pg" disabled={safePage === totalPages} onClick={() => setPage((current) => Math.min(totalPages, current + 1))}><Icon name="chevRight" style={{ width: 13, height: 13 }} /></button>
                  <button className="pg" disabled={safePage === totalPages} onClick={() => setPage(totalPages)}>{">>"}</button>
                </div>
              </div>
            </Card>
          </div>

          <aside className="anomaly-rail">
            <Card
              title="Alerts"
              icon="bell"
              iconTone="red"
              sub="Critical and High severity events"
              actions={openAlertCount > 0 ? <span className="alert-count-badge">{openAlertCount}</span> : undefined}
            >
              <AlertFeed
                events={visibleTimeline.items}
                statuses={statuses}
                onAcknowledge={acknowledge}
                onResolve={resolve}
                onReopen={reopen}
                onSelect={setSelected}
              />
            </Card>

            <Card title="Type Profile" icon="layers" sub="Most common event classes">
              <div className="anomaly-type-list">
                {typeEntries.length === 0 && <div className="empty" style={{ padding: 18 }}>No anomaly types match.</div>}
                {typeEntries.map(([type, count]) => {
                  const ratio = visibleOverview.total_anomalies ? Math.max(4, (count / visibleOverview.total_anomalies) * 100) : 0;
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

      {visibleSelected && <AnomalyEventDrawer event={visibleSelected} simNow={simNow} onClose={() => setSelected(null)} />}
    </div>
  );
}
