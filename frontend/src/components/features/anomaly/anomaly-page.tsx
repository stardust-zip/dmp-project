"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { buildUnifiedAnomalyTimeline, EChart } from "@/components/common/charts";
import { Icon } from "@/components/common/icons";
import { AnomalySeverityBadge, Card, Field, Select, Spinner, toneStyle } from "@/components/common/primitives";
import { AlertFeed } from "@/components/features/anomaly/anomaly-alert-feed";
import { AnomalyEventDrawer } from "@/components/features/anomaly/anomaly-event-drawer";
import { useAuth } from "@/components/auth/auth-provider";
import { useAlerts } from "@/hooks/use-alerts";
import { getAnomalyFacets, getAnomalyTimeline, type AnomalyQuery } from "@/lib/anomaly-api";
import { readStoredSession } from "@/lib/auth-api";
import { clock, displayLocationName, fmt, fmtKwh } from "@/lib/format";
import { setIsPlaying, useSimulationStore, type SimBounds } from "@/lib/simulation-store";
import type { AnomalyEvent, AnomalyEventsResponse, AnomalyFacets, AnomalyOverview, AnomalySeverity, AnomalyTimelineGap, AnomalyTimelineResponse, Tone } from "@/types";

type SortKey = "severity" | "newest" | "oldest";

type Filters = {
  site: string;
  building: string;
  primaryUsage: string;
  severity: string;
  type: string;
  sort: SortKey;
};

const PER_PAGE = 10;
const SIMULATION_FETCH_LIMIT = 5000;
const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;
const TIMELINE_ZOOM_MS = 7 * DAY_MS;
const SIMULATION_RANGE_QUERY = { start: "2017-10-01T00:00:00", end: "2017-12-31T23:00:00" } as const;
const SEVERITY_RANK: Record<AnomalySeverity, number> = { Critical: 0, High: 1, Medium: 2, Low: 3 };
const DEFAULT_FILTERS: Filters = { site: "all", building: "all", primaryUsage: "all", severity: "all", type: "all", sort: "severity" };

// Building IDs follow the format {site_id}_{primaryUsage}_{buildingName}.
// This extracts the site and primary usage portions when present.
function parseScopeId(id: string): { siteId: string; primaryUsage: string | null } {
  const first = id.indexOf("_");
  if (first < 0) return { siteId: id, primaryUsage: null };
  const second = id.indexOf("_", first + 1);
  if (second < 0) return { siteId: id, primaryUsage: null };
  const raw = id.slice(first + 1, second);
  return { siteId: id.slice(0, first), primaryUsage: raw.charAt(0).toUpperCase() + raw.slice(1) };
}
const SORT_KEYS = new Set<SortKey>(["severity", "newest", "oldest"]);

const EMPTY_TIMELINE: AnomalyTimelineResponse = { items: [], points: [], gaps: [] };

function queryValue(search: URLSearchParams, ...keys: string[]) {
  for (const key of keys) {
    const value = search.get(key)?.trim();
    if (value) return value;
  }
  return "all";
}

function filtersFromSearch(search: string): Filters {
  const params = new URLSearchParams(search);
  const sort = queryValue(params, "sort");
  return normalizeFilters({
    ...DEFAULT_FILTERS,
    site: queryValue(params, "site", "site_id"),
    building: queryValue(params, "building", "building_id"),
    primaryUsage: queryValue(params, "primaryUsage", "primary_usage", "primaryspaceusage"),
    severity: queryValue(params, "severity"),
    type: queryValue(params, "type"),
    sort: SORT_KEYS.has(sort as SortKey) ? (sort as SortKey) : DEFAULT_FILTERS.sort,
  });
}

function normalizeFilters(filters: Filters): Filters {
  if (filters.site === "all") {
    return { ...filters, primaryUsage: "all", building: "all" };
  }
  if (filters.primaryUsage === "all") {
    return { ...filters, building: "all" };
  }
  return filters;
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

function SelectionGate({ siteSelected, primaryUsageSelected }: { siteSelected: boolean; primaryUsageSelected: boolean }) {
  const title = !siteSelected
    ? "Select a site to begin"
    : primaryUsageSelected
      ? "Select a building to begin"
      : "Select primary usage to continue";
  const description = !siteSelected
    ? "Start by selecting a site, then choose a primary usage and building to analyze its anomaly history."
    : primaryUsageSelected
      ? "Choose a building from the dropdown above to load its anomaly timeline, event log, and severity distribution."
      : "Choose a primary usage first so the building list only shows relevant assets.";

  return (
    <div className="anomaly-gate">
      <div className="anomaly-gate-inner">
        <div className="anomaly-gate-icon">
          <Icon name="building" />
        </div>
        <h2 className="anomaly-gate-title">{title}</h2>
        <p className="anomaly-gate-desc">{description}</p>
      </div>
    </div>
  );
}

function timelineDisabledReason(loading: boolean, bounds: SimBounds | null, simNow: number | null) {
  if (loading) return null;
  if (!bounds || simNow == null) return "No replay data is available for this building in Oct-Dec 2017.";
  if (bounds.end <= bounds.start) return "Replay needs more than one timestamp in Oct-Dec 2017.";
  return null;
}

function followZoomWindow(bounds: SimBounds | null, simNow: number | null): SimBounds | null {
  if (!bounds || simNow == null || bounds.end <= bounds.start) return null;
  const windowSize = Math.min(TIMELINE_ZOOM_MS, bounds.end - bounds.start);
  const latestStart = bounds.end - windowSize;
  const cursorMidpointStart = simNow - windowSize / 2;
  const start = Math.max(bounds.start, Math.min(cursorMidpointStart, latestStart));
  return { start, end: start + windowSize };
}

export function AnomalyPage() {
  const searchParams = useSearchParams();
  const searchParamString = searchParams.toString();
  const [filters, setFilters] = useState<Filters>(() => {
    if (typeof window === "undefined") return DEFAULT_FILTERS;
    const base = filtersFromSearch(window.location.search);
    const stored = readStoredSession();
    if (stored?.user.role === "Operator" && stored.user.assignedSiteIds.length > 0) {
      const siteIds = new Set(stored.user.assignedSiteIds.map((id) => parseScopeId(id).siteId));
      if (siteIds.size === 1) return normalizeFilters({ ...base, site: [...siteIds][0] });
    }
    return base;
  });
  const [page, setPage] = useState(1);
  const [facets, setFacets] = useState<AnomalyFacets>({ sites: [], buildings: [], severities: ["Critical", "High", "Medium", "Low"], types: [], primary_usage_types: [] });
  const [siteFacetsBySite, setSiteFacetsBySite] = useState<Record<string, AnomalyFacets>>({});
  const [siteEventsBySite, setSiteEventsBySite] = useState<Record<string, AnomalyEvent[]>>({});
  const [rawTimeline, setRawTimeline] = useState<AnomalyTimelineResponse>(EMPTY_TIMELINE);
  const { simNow, bounds: simBounds, isPlaying } = useSimulationStore();
  const [selected, setSelected] = useState<AnomalyEvent | null>(null);
  const [loading, setLoading] = useState(false);
  const [timelineLoaded, setTimelineLoaded] = useState(false);
  const autoEventId = useMemo(() => searchParams.get("event") ?? null, [searchParams]);
  const [error, setError] = useState<string | null>(null);
  const { statuses, acknowledge, resolve, reopen } = useAlerts();
  const { session } = useAuth();
  const lockedSite = useMemo(() => {
    const user = session?.user;
    if (user?.role !== "Operator" || user.assignedSiteIds.length === 0) return null;
    const siteIds = new Set(user.assignedSiteIds.map((id) => parseScopeId(id).siteId));
    return siteIds.size === 1 ? [...siteIds][0] : null;
  }, [session]);
  const lockedPrimaryUsage = useMemo(() => {
    if (!lockedSite || !session?.user) return null;
    const { assignedSiteIds } = session.user;
    if (assignedSiteIds.length === 1) {
      const { primaryUsage } = parseScopeId(assignedSiteIds[0]);
      if (primaryUsage) return primaryUsage;
    }
    const siteF = siteFacetsBySite[lockedSite];
    if (!siteF || siteF.buildings.length !== 1) return null;
    return siteF.primary_usage_types[0] ?? null;
  }, [lockedSite, session, siteFacetsBySite]);

  const replayQuery = useMemo<AnomalyQuery>(() => ({
    site: filters.site,
    building: filters.building,
    severity: filters.severity,
    type: filters.type,
    limit: SIMULATION_FETCH_LIMIT,
    ...SIMULATION_RANGE_QUERY,
  }), [filters.site, filters.building, filters.severity, filters.type]);

  const isPrimaryUsageSelected = filters.primaryUsage !== "all";
  const isGated = filters.building === "all";
  const replayDisabledReason = timelineLoaded ? timelineDisabledReason(loading, simBounds, simNow) : null;
  const timelineZoom = useMemo(() => followZoomWindow(simBounds, simNow), [simBounds, simNow]);
  const shouldFollowTimeline = isPlaying && timelineZoom != null;
  const visibleTimeline = useMemo(() => (simNow == null ? EMPTY_TIMELINE : timelineUntil(rawTimeline, simNow)), [rawTimeline, simNow]);
  const visibleOverview = useMemo(() => overviewFromEvents(visibleTimeline.items), [visibleTimeline.items]);
  const sortedEvents = useMemo(() => sortEvents(visibleTimeline.items, filters.sort), [filters.sort, visibleTimeline.items]);
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
      const usages = fromFacets.length > 0
        ? fromFacets
        : [...new Set(siteEvents.map((event) => event.primary_space_usage).filter(Boolean))].sort() as string[];
      return filters.primaryUsage !== "all" && !usages.includes(filters.primaryUsage)
        ? [filters.primaryUsage, ...usages]
        : usages;
    },
    [activeFacets.primary_usage_types, filters.primaryUsage, siteEvents],
  );
  const filteredBuildings = useMemo(() => {
    const withSelected = (buildings: string[]) => (
      filters.building !== "all" && !buildings.includes(filters.building)
        ? [filters.building, ...buildings]
        : buildings
    );
    if (filters.primaryUsage === "all") return withSelected(activeFacets.buildings);
    const source = siteEvents.filter((event) => event.primary_space_usage === filters.primaryUsage);
    const fromEvents = [...new Set(source.map((event) => event.building_id))].sort();
    return withSelected(fromEvents.length > 0 ? fromEvents : activeFacets.buildings);
  }, [activeFacets.buildings, filters.building, filters.primaryUsage, siteEvents]);
  const lockedBuilding = filteredBuildings.length === 1 ? filteredBuildings[0] : null;

  useEffect(() => {
    const nextFilters = filtersFromSearch(searchParamString ? `?${searchParamString}` : "");
    const withLocks = lockedSite ? normalizeFilters({ ...nextFilters, site: lockedSite }) : nextFilters;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFilters(withLocks);
    setPage(1);
    setSelected(null);
    setTimelineLoaded(false);
    setRawTimeline(EMPTY_TIMELINE);
    window.requestAnimationFrame(() => {
      if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    });
  }, [searchParamString, lockedSite]);

  useEffect(() => {
    if (!lockedPrimaryUsage) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFilters((current) => {
      if (current.primaryUsage !== "all") return current;
      return normalizeFilters({ ...current, primaryUsage: lockedPrimaryUsage });
    });
  }, [lockedPrimaryUsage]);

  useEffect(() => {
    if (!lockedBuilding) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFilters((current) => {
      if (current.building === lockedBuilding) return current;
      return { ...current, building: lockedBuilding };
    });
  }, [lockedBuilding]);

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
    if (filters.site === "all" || filters.building !== "all" || siteEventsBySite[filters.site]) return;

    const controller = new AbortController();
    getAnomalyTimeline({ site: filters.site, limit: 1500 }, controller.signal)
      .then((data) => {
        setSiteEventsBySite((current) => ({ ...current, [filters.site]: data.items }));
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") console.error(err);
      });
    return () => controller.abort();
  }, [filters.building, filters.site, siteEventsBySite]);

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

  // Fetch event data only once a specific building is chosen
  useEffect(() => {
    if (replayQuery.building === "all") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRawTimeline(EMPTY_TIMELINE);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setTimelineLoaded(false);
    setError(null);
    getAnomalyTimeline(replayQuery, controller.signal)
      .then((nextTimeline) => {
        setRawTimeline(nextTimeline);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
          setTimelineLoaded(true);
        }
      });

    return () => controller.abort();
  }, [replayQuery]);

  // Auto-open drawer when arriving from dashboard with an event param.
  useEffect(() => {
    if (!autoEventId || !timelineLoaded) return;
    const event = rawTimeline.items.find((e) => e.id === autoEventId);
    if (event) setSelected(event);
  }, [autoEventId, timelineLoaded, rawTimeline.items]);

  const set = (key: keyof Filters, value: string) => {
    setFilters((current) => normalizeFilters({ ...current, [key]: value }));
    setPage(1);
    setSelected(null);
    setIsPlaying(false);
    setTimelineLoaded(false);
  };

  const siteOptions = filters.site !== "all" && !facets.sites.includes(filters.site) ? [filters.site, ...facets.sites] : facets.sites;
  const primaryUsageOptions = filters.site === "all"
    ? []
    : [{ value: "all" as const, label: "All Usage Types" }, ...filteredPrimaryUsages.map((usage) => ({ value: usage, label: usage }))];
  const buildingOptions = filters.site === "all" || !isPrimaryUsageSelected
    ? []
    : [{ value: "all" as const, label: "All Buildings" }, ...filteredBuildings.map((building) => ({ value: building, label: buildingLabel(building) }))];

  return (
    <div className="page anomaly-page">
      <Card
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
              }}
              disabled={!!lockedSite}
              options={[{ value: "all", label: "All Sites" }, ...siteOptions.map((site) => ({ value: site, label: site }))]}
              searchable={!lockedSite}
              searchPlaceholder="Search sites..."
            />
          </Field>
          <Field label="Primary Usage">
            <Select
              value={filters.primaryUsage}
              onChange={(value) => {
                set("primaryUsage", value);
                set("building", "all");
              }}
              disabled={filters.site === "all" || primaryUsageOptions.length === 0 || !!lockedPrimaryUsage}
              options={primaryUsageOptions}
              searchable={!lockedPrimaryUsage}
              searchPlaceholder="Search usage..."
            />
          </Field>
          <Field label="Building">
            <Select
              value={filters.building}
              onChange={(value) => set("building", value)}
              disabled={filters.site === "all" || !isPrimaryUsageSelected || filteredBuildings.length === 0 || !!lockedBuilding}
              options={buildingOptions}
              searchable={!lockedBuilding}
              searchPlaceholder="Search buildings..."
            />
          </Field>
          <Field label="Severity">
            <Select value={filters.severity} onChange={(value) => set("severity", value)} disabled={isGated} options={[{ value: "all", label: "All Severities" }, ...facets.severities.map((severity) => ({ value: severity, label: severity }))]} />
          </Field>
          <Field label="Type">
            <Select value={filters.type} onChange={(value) => set("type", value)} disabled={isGated} options={[{ value: "all", label: "All Types" }, ...facets.types.map((type) => ({ value: type, label: type }))]} />
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
        <SelectionGate siteSelected={filters.site !== "all"} primaryUsageSelected={isPrimaryUsageSelected} />
      ) : (
        <div className="grid anomaly-main-grid">
          <div className="anomaly-workspace">
            <Card
              title="Timeline"
              icon="pulse"
              iconTone="red"
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
              {replayDisabledReason && (
                <div className="empty compact anomaly-replay-note">
                  <Icon name="info" />
                  <span>{replayDisabledReason}</span>
                </div>
              )}
              {loading ? (
                <div className="empty"><Spinner /> Loading timeline...</div>
              ) : (
                <EChart
                  build={buildUnifiedAnomalyTimeline(visibleTimeline, {
                    cursorTime: simNow ?? undefined,
                    axisMin: simBounds?.start,
                    axisMax: simBounds?.end,
                    zoomStart: shouldFollowTimeline ? timelineZoom.start : undefined,
                    zoomEnd: shouldFollowTimeline ? timelineZoom.end : undefined,
                    futurePoints: simNow == null ? [] : rawTimeline.points.filter((p) => timeOf(p.timestamp) >= simNow && timeOf(p.timestamp) <= simNow + 6 * 60 * 60 * 1000),
                  })}
                  deps={[visibleTimeline, simNow, simBounds?.start, simBounds?.end, shouldFollowTimeline, timelineZoom?.start, timelineZoom?.end, rawTimeline.points]}
                  themeKey="unified-anomaly"
                  height={312}
                  preserveDataZoom={!shouldFollowTimeline}
                  onChartClick={(params) => {
                    const p = params as { seriesName?: string; data?: { event?: AnomalyEvent } };
                    if (p.seriesName === "Anomaly" && p.data?.event) {
                      setSelected(p.data.event);
                    }
                  }}
                />
              )}
            </Card>

            <Card
              title="Event Log"
              icon="table"
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

            <Card title="Type Profile" icon="layers">
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
