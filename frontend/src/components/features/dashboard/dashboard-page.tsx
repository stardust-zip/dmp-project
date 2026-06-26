"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { buildUnifiedAnomalyTimeline, EChart } from "@/components/common/charts";
import { Card, KpiCard, Select, Spinner } from "@/components/common/primitives";
import { getAnomalyEvents, getAnomalyFacets, getAnomalyTimeline } from "@/lib/anomaly-api";
import { displayLocationName, fmtKwh, timeAgo } from "@/lib/format";
import { KPIS } from "@/lib/mock-data";
import { useSimulationStore, type SimBounds } from "@/lib/simulation-store";
import type { AnomalyEvent, AnomalyFacets, AnomalyTimelineResponse } from "@/types";

const SEVERITY_RANK: Record<string, number> = { Critical: 0, High: 1, Medium: 2, Low: 3 };
const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;
const TIMELINE_ZOOM_MS = 7 * DAY_MS;
const SIMULATION_FETCH_LIMIT = 5000;
const SIMULATION_RANGE_QUERY = { start: "2017-10-01T00:00:00", end: "2017-12-31T23:00:00" } as const;
const EMPTY_TIMELINE: AnomalyTimelineResponse = { items: [], points: [], gaps: [] };

function timeOf(value: string) {
  return new Date(value).getTime();
}

function localTimestamp(ts: number) {
  const d = new Date(ts);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function clampGap(gap: AnomalyTimelineResponse["gaps"][number], simNow: number): AnomalyTimelineResponse["gaps"][number] | null {
  const start = timeOf(gap.start_time);
  if (!Number.isFinite(start) || start > simNow) return null;
  const end = Math.min(timeOf(gap.end_time), simNow);
  return { ...gap, end_time: localTimestamp(end) };
}

function timelineUntil(timeline: AnomalyTimelineResponse, simNow: number): AnomalyTimelineResponse {
  return {
    points: timeline.points.filter((point) => timeOf(point.timestamp) <= simNow),
    items: timeline.items.filter((event) => timeOf(event.start_time) <= simNow),
    gaps: timeline.gaps.map((gap) => clampGap(gap, simNow)).filter((gap): gap is AnomalyTimelineResponse["gaps"][number] => gap != null),
  };
}

function followZoomWindow(bounds: SimBounds | null, simNow: number | null): SimBounds | null {
  if (!bounds || simNow == null || bounds.end <= bounds.start) return null;
  const windowSize = Math.min(TIMELINE_ZOOM_MS, bounds.end - bounds.start);
  const latestStart = bounds.end - windowSize;
  const cursorMidpointStart = simNow - windowSize / 2;
  const start = Math.max(bounds.start, Math.min(cursorMidpointStart, latestStart));
  return { start, end: start + windowSize };
}

function dayBoundsUTC(ts: number, offsetDays: number): [number, number] {
  const d = new Date(ts);
  const start = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + offsetDays, 0, 0, 0);
  const end = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + offsetDays + 1, 0, 0, 0) - 1;
  return [start, end];
}

function avgActualKwh(points: AnomalyTimelineResponse["points"], from: number, to: number): number | null {
  const vals = points
    .filter((p) => { const t = new Date(p.timestamp).getTime(); return t >= from && t <= to && p.actual_value != null; })
    .map((p) => p.actual_value as number);
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
}

function avgExpectedKwh(points: AnomalyTimelineResponse["points"], from: number, to: number): number | null {
  const vals = points
    .filter((p) => { const t = new Date(p.timestamp).getTime(); return t >= from && t <= to && p.expected_value != null; })
    .map((p) => p.expected_value as number);
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
}

function pctDelta(a: number, b: number): number {
  if (b === 0) return 0;
  return Math.round(((a - b) / b) * 1000) / 10;
}

function toneColor(tone: string) {
  if (tone === "red") return "var(--red)";
  if (tone === "orange") return "var(--orange)";
  if (tone === "accent") return "var(--accent-600)";
  return "var(--muted)";
}

export function DashboardPage() {
  // API data
  const [recentEvents, setRecentEvents] = useState<AnomalyEvent[]>([]);
  const [facets, setFacets] = useState<AnomalyFacets>({ sites: [], buildings: [], severities: [], types: [], primary_usage_types: [] });

  // Building picker
  const [selectedBuilding, setSelectedBuilding] = useState<string>("all");

  // Simulator
  const [rawTimeline, setRawTimeline] = useState<AnomalyTimelineResponse>(EMPTY_TIMELINE);
  const { simNow, bounds: simBounds, isPlaying } = useSimulationStore();

  // Loading / error
  const [loadingDash, setLoadingDash] = useState(true);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [buildingSort, setBuildingSort] = useState<"critical" | "total">("critical");
  const [breakdownRange, setBreakdownRange] = useState<"24h" | "7d" | "30d">("7d");

  const router = useRouter();

  // On-mount fetch (3 parallel)
  useEffect(() => {
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoadingDash(true);
    Promise.all([
      getAnomalyEvents({ sort: "oldest", ...SIMULATION_RANGE_QUERY }, controller.signal),
      getAnomalyFacets(undefined, controller.signal),
    ])
      .then(([evs, fcts]) => {
        setRecentEvents(evs.items);
        setFacets(fcts);
        // Auto-select for operators with exactly 1 building
        if (fcts.buildings.length === 1) {
          setSelectedBuilding(fcts.buildings[0]);
        }
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingDash(false);
      });
    return () => controller.abort();
  }, []);

  // Timeline fetch when building selected
  useEffect(() => {
    if (selectedBuilding === "all") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRawTimeline(EMPTY_TIMELINE);
      return;
    }
    const controller = new AbortController();
    setLoadingTimeline(true);
    getAnomalyTimeline(
      { building: selectedBuilding, limit: SIMULATION_FETCH_LIMIT, ...SIMULATION_RANGE_QUERY },
      controller.signal,
    )
      .then((tl) => {
        setRawTimeline(tl);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingTimeline(false);
      });
    return () => controller.abort();
  }, [selectedBuilding]);

  // Derived values
  const visibleTimeline = useMemo(
    () => (simNow == null ? EMPTY_TIMELINE : timelineUntil(rawTimeline, simNow)),
    [rawTimeline, simNow],
  );
  const timelineZoom = useMemo(() => followZoomWindow(simBounds, simNow), [simBounds, simNow]);
  const shouldFollowTimeline = isPlaying && timelineZoom != null;

  const visibleDashboardEvents = useMemo(
    () => (simNow == null ? [] : recentEvents.filter((event) => timeOf(event.start_time) <= simNow)),
    [recentEvents, simNow],
  );

  const consumptionKpis = useMemo(() => {
    if (selectedBuilding === "all" || simNow == null) {
      return { current: null, currentExpected: null, today: null, yesterday: null, dayBefore: null, forecast: null };
    }
    const [todayStart] = dayBoundsUTC(simNow, 0);
    const [yestStart, yestEnd] = dayBoundsUTC(simNow, -1);
    const [dayBeforeStart, dayBeforeEnd] = dayBoundsUTC(simNow, -2);
    const latestPoint = [...visibleTimeline.points].reverse().find((p) => p.actual_value != null);
    return {
      current:         latestPoint?.actual_value ?? null,
      currentExpected: latestPoint?.expected_value ?? null,
      today:     avgActualKwh(visibleTimeline.points, todayStart, simNow),
      yesterday: avgActualKwh(visibleTimeline.points, yestStart, yestEnd),
      dayBefore: avgActualKwh(rawTimeline.points, dayBeforeStart, dayBeforeEnd),
      forecast:  avgExpectedKwh(rawTimeline.points, simNow, simNow + 6 * HOUR_MS),
    };
  }, [selectedBuilding, simNow, visibleTimeline.points, rawTimeline.points]);

  const breakdownEvents = useMemo(() => {
    if (simNow == null) return [];
    const windowMs = breakdownRange === "24h" ? DAY_MS : breakdownRange === "7d" ? 7 * DAY_MS : 30 * DAY_MS;
    const cutoff = simNow - windowMs;
    return visibleDashboardEvents.filter((e) => timeOf(e.start_time) >= cutoff);
  }, [visibleDashboardEvents, simNow, breakdownRange]);

  // Top 3 buildings by critical anomaly count within the breakdown window.
  const topCriticalBuildings = useMemo(() => {
    const byBuilding = new Map<string, { count: number; latestEvent: AnomalyEvent }>();
    breakdownEvents
      .filter((e) => e.severity === "Critical")
      .forEach((e) => {
        const existing = byBuilding.get(e.building_id);
        if (!existing) {
          byBuilding.set(e.building_id, { count: 1, latestEvent: e });
        } else {
          const isNewer = new Date(e.start_time).getTime() > new Date(existing.latestEvent.start_time).getTime();
          byBuilding.set(e.building_id, { count: existing.count + 1, latestEvent: isNewer ? e : existing.latestEvent });
        }
      });
    return [...byBuilding.entries()]
      .sort((a, b) => b[1].count - a[1].count)
      .slice(0, 3)
      .map(([buildingId, { count, latestEvent }]) => ({ buildingId, count, latestEvent }));
  }, [breakdownEvents]);

  // Building-level status rows update with the global simulation cursor.
  const buildingStatusRows = useMemo(() => {
    const byBuilding = new Map<string, AnomalyEvent[]>();
    visibleDashboardEvents.forEach((e) => {
      const arr = byBuilding.get(e.building_id) ?? [];
      arr.push(e);
      byBuilding.set(e.building_id, arr);
    });
    return facets.buildings
      .map((buildingId) => {
        const events = byBuilding.get(buildingId) ?? [];
        const criticalCount = events.filter((e) => e.severity === "Critical").length;
        const hasHigh = events.some((e) => e.severity === "High");
        const status = criticalCount > 0 ? "red" : hasHigh ? "yellow" : "green";
        const ref = events[0];
        return { buildingId, status, totalCount: events.length, criticalCount, siteId: ref?.site_id ?? null, primaryUsage: ref?.primary_space_usage ?? null };
      })
      .sort((a, b) =>
        buildingSort === "critical"
          ? b.criticalCount - a.criticalCount || b.totalCount - a.totalCount
          : b.totalCount - a.totalCount || b.criticalCount - a.criticalCount
      );
  }, [visibleDashboardEvents, facets.buildings, buildingSort]);

  // Building picker options
  const showBuildingPicker = facets.buildings.length > 1;
  const buildingOptions = useMemo(
    () => [
      { value: "all", label: "Select a building..." },
      ...facets.buildings.map((b) => ({ value: b, label: displayLocationName(null, b) })),
    ],
    [facets.buildings],
  );

  // KPI strip — critical count and consumption stats track simNow
  const kpis = useMemo(() => {
    const [todayStartMs] = simNow != null ? dayBoundsUTC(simNow, 0) : [null];
    const critical = visibleDashboardEvents.filter(
      (e) => e.severity === "Critical" && todayStartMs != null && timeOf(e.start_time) >= todayStartMs,
    ).length;

    const { current, currentExpected, today, yesterday, dayBefore, forecast } = consumptionKpis;

    return KPIS.map((kpi) => {
      if (kpi.key === "current") {
        if (current == null) return { ...kpi, value: "-", delta: 0, deltaLabel: "" };
        const delta = currentExpected != null && currentExpected !== 0 ? pctDelta(current, currentExpected) : 0;
        return { ...kpi, value: fmtKwh(current), delta, deltaLabel: "vs expected" };
      }
      if (kpi.key === "today") {
        if (today == null) return { ...kpi, value: "-", delta: 0, deltaLabel: "" };
        return { ...kpi, value: fmtKwh(today), delta: yesterday != null ? pctDelta(today, yesterday) : 0, deltaLabel: "vs yesterday" };
      }
      if (kpi.key === "yest") {
        if (yesterday == null) return { ...kpi, value: "-", delta: 0, deltaLabel: "" };
        return { ...kpi, value: fmtKwh(yesterday), delta: dayBefore != null ? pctDelta(yesterday, dayBefore) : 0, deltaLabel: "vs 2 days ago" };
      }
      if (kpi.key === "forecast") {
        if (forecast == null) return { ...kpi, value: "-", delta: 0, deltaLabel: "" };
        const base = today ?? yesterday;
        return { ...kpi, value: fmtKwh(forecast), delta: base != null ? pctDelta(forecast, base) : 0, deltaLabel: "vs now" };
      }
      if (kpi.key === "crit" || kpi.label?.toLowerCase().includes("critical")) {
        return { ...kpi, value: String(critical) };
      }
      return kpi;
    });
  }, [visibleDashboardEvents, simNow, consumptionKpis]);

  // Severity items update with the global simulation cursor.
  const severityItems = useMemo(() => {
    const counts = { Critical: 0, High: 0, Medium: 0, Low: 0 };
    breakdownEvents.forEach((event) => {
      if (event.severity in counts) counts[event.severity as keyof typeof counts] += 1;
    });
    return [
      { key: "critical", label: "Critical", value: counts.Critical ?? 0, tone: "red" },
      { key: "high",     label: "High",     value: counts.High ?? 0,     tone: "orange" },
      { key: "medium",   label: "Medium",   value: counts.Medium ?? 0,   tone: "accent" },
      { key: "low",      label: "Low",      value: counts.Low ?? 0,      tone: "accent" },
    ] as const;
  }, [breakdownEvents]);

  return (
    <div className="page">
      <div className="page-head">
      </div>


      <div className="grid kpi-summary">
        {kpis.map((kpi) => (
          <KpiCard key={kpi.key} kpi={kpi} />
        ))}
      </div>

      {error && (
        <div className="empty" style={{ marginBottom: "var(--gap)" }}>
          Could not load dashboard data. Confirm the backend is running.
          <div className="mono" style={{ marginTop: 6 }}>{error}</div>
        </div>
      )}

      <div className="grid dashboard-chart-grid" style={{ marginBottom: "var(--gap)" }}>
        <Card
          title="Energy Consumption Trend"
          icon="pulse"
          actions={
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div className="legend" style={{ margin: 0 }}>
                <span className="leg" style={{ color: "var(--accent-600)" }}>
                  <i style={{ background: "var(--accent-600)" }} /> Actual Consumption
                </span>
                <span className="leg">
                  <i className="dash" style={{ color: "var(--muted)" }} /> Expected Baseline
                </span>
              </div>
              {showBuildingPicker ? (
                <div style={{ minWidth: 220 }}>
                  <Select
                    value={selectedBuilding}
                    onChange={setSelectedBuilding}
                    options={buildingOptions}
                    searchable
                    searchPlaceholder="Search buildings..."
                  />
                </div>
              ) : facets.buildings.length === 1 ? (
                <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
                  {displayLocationName(null, facets.buildings[0])}
                </span>
              ) : null}
            </div>
          }
        >
          {selectedBuilding === "all" ? (
            loadingDash
              ? <div className="empty" style={{ height: 296 }}><Spinner /> Loading...</div>
              : <div className="empty" style={{ height: 296 }}>Select a building to view its energy consumption trend.</div>
          ) : loadingTimeline ? (
            <div className="empty" style={{ height: 296 }}><Spinner /> Loading timeline...</div>
          ) : (
            <EChart
              build={buildUnifiedAnomalyTimeline(visibleTimeline, {
                cursorTime: simNow ?? undefined,
                axisMin: simBounds?.start,
                axisMax: simBounds?.end,
                zoomStart: shouldFollowTimeline ? timelineZoom.start : undefined,
                zoomEnd: shouldFollowTimeline ? timelineZoom.end : undefined,
                futurePoints: simNow == null ? [] : rawTimeline.points.filter(
                  (p) => new Date(p.timestamp).getTime() >= simNow && new Date(p.timestamp).getTime() <= simNow + 6 * HOUR_MS,
                ),
                showMarkers: false,
              })}
              deps={[visibleTimeline, simNow, simBounds?.start, simBounds?.end, shouldFollowTimeline, timelineZoom?.start, timelineZoom?.end, rawTimeline.points]}
              themeKey="dashboard-timeline"
              height={296}
              preserveDataZoom={!shouldFollowTimeline}
            />
          )}
        </Card>

        <Card
          title="Anomaly Breakdown"
          icon="pulse"
          iconTone="orange"
          actions={
            <div style={{ display: "flex", gap: 4 }}>
              {(["24h", "7d", "30d"] as const).map((r) => (
                <button
                  key={r}
                  className={`btn btn-sm${breakdownRange === r ? " btn-primary" : ""}`}
                  type="button"
                  onClick={() => setBreakdownRange(r)}
                >
                  {r}
                </button>
              ))}
            </div>
          }
        >
          <div className="anom-sev-strip">
            {severityItems.map((s) => (
              <div key={s.key} className="anom-sev-item">
                <span className="anom-sev-val" style={{ color: toneColor(s.tone) }}>{s.value}</span>
                <span className="anom-sev-label">{s.label}</span>
              </div>
            ))}
          </div>

          <div className="sec-label" style={{ marginTop: 16 }}>Needs attention</div>
          <div className="anom-needs-list">
            {topCriticalBuildings.length === 0 && !loadingDash && (
              <div className="empty" style={{ padding: "12px 0" }}>No critical alerts</div>
            )}
            {topCriticalBuildings.map(({ buildingId, count, latestEvent }) => {
              const params = new URLSearchParams({ site: latestEvent.site_id, building: buildingId });
              if (latestEvent.primary_space_usage) params.set("primaryUsage", latestEvent.primary_space_usage);
              return (
                <div
                  key={buildingId}
                  className="anom-needs-row"
                  style={{ cursor: "pointer" }}
                  onClick={() => router.push(`/anomaly?${params.toString()}`)}
                >
                  <span className="badge badge-critical"><i className="bdot" />critical</span>
                  <span className="anom-needs-info">
                    <b>{displayLocationName(null, buildingId)}</b>
                    <small>{count} critical anomal{count === 1 ? "y" : "ies"}</small>
                  </span>
                  <span className="mono anom-needs-time">{timeAgo(new Date(latestEvent.start_time).getTime())}</span>
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      <div className="grid dashboard-lower-grid">
        <Card
          title="Recent Alerts"
          icon="bell"
          iconTone="orange"
          noBody
        >
          <div className="table-scroll">
            <table className="tbl tbl-clickable">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Site</th>
                  <th>Building</th>
                  <th>Type</th>
                  <th>Severity</th>
                </tr>
              </thead>
              <tbody>
                {loadingDash && (
                  <tr>
                    <td colSpan={5}><div className="empty"><Spinner /> Loading...</div></td>
                  </tr>
                )}
                {!loadingDash && visibleDashboardEvents.length === 0 && (
                  <tr>
                    <td colSpan={5}><div className="empty">No alerts at this point in time.</div></td>
                  </tr>
                )}
                {[...visibleDashboardEvents].sort((a, b) =>
                  (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9) ||
                  new Date(b.start_time).getTime() - new Date(a.start_time).getTime()
                ).slice(0, 8).map((event) => {
                  const params = new URLSearchParams({ site: event.site_id, building: event.building_id, event: event.id });
                  if (event.primary_space_usage) params.set("primaryUsage", event.primary_space_usage);
                  return (
                  <tr key={event.id} onClick={() => router.push(`/anomaly?${params.toString()}`)}>
                    <td className="mono" style={{ color: "var(--muted)" }}>{timeAgo(new Date(event.start_time).getTime())}</td>
                    <td>{event.site_id}</td>
                    <td className="t-strong">{displayLocationName(null, event.building_id)}</td>
                    <td>{event.type}</td>
                    <td>
                      <span className={`badge badge-anomaly-${event.severity.toLowerCase()}`}>
                        <i className="bdot" />{event.severity}
                      </span>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>

        <Card
          title="Site Status"
          icon="map"
          actions={
            <div style={{ width: 165 }}>
              <Select
                value={buildingSort}
                onChange={setBuildingSort}
                options={[
                  { value: "critical", label: "By Critical Anomalies" },
                  { value: "total",    label: "By Total Anomalies" },
                ]}
              />
            </div>
          }
        >
          <div className="site-status-list" style={{ overflowY: "auto", maxHeight: 320 }}>
            {loadingDash && <div className="empty"><Spinner /> Loading...</div>}
            {!loadingDash && buildingStatusRows.length === 0 && (
              <div className="empty">No site data available.</div>
            )}
            {buildingStatusRows.map((row) => {
              const params = new URLSearchParams();
              if (row.siteId) params.set("site", row.siteId);
              params.set("building", row.buildingId);
              if (row.primaryUsage) params.set("primaryUsage", row.primaryUsage);
              return (
                <div
                  key={row.buildingId}
                  className="site-status-row"
                  style={{ cursor: "pointer" }}
                  onClick={() => router.push(`/anomaly?${params.toString()}`)}
                >
                  <div className="site-status-info">
                    <b>{displayLocationName(null, row.buildingId)}</b>
                    <small>{row.criticalCount > 0 ? `${row.criticalCount} critical` : "No critical"}</small>
                  </div>
                  <span className="mono" style={{ fontSize: 12, color: "var(--muted)", marginLeft: "auto" }}>
                    {row.totalCount} open
                  </span>
                </div>
              );
            })}
          </div>
        </Card>
      </div>
    </div>
  );
}
