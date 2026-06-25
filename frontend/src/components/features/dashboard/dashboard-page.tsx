"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { buildUnifiedAnomalyTimeline, EChart } from "@/components/common/charts";
import { Icon } from "@/components/common/icons";
import { Card, KpiCard, Select, Spinner } from "@/components/common/primitives";
import { getAnomalyOverview, getAnomalyEvents, getAnomalyFacets, getAnomalyTimeline } from "@/lib/anomaly-api";
import { displayLocationName, timeAgo } from "@/lib/format";
import { KPIS } from "@/lib/mock-data";
import { useSimulationStore, type SimBounds } from "@/lib/simulation-store";
import type { AnomalyEvent, AnomalyFacets, AnomalyOverview, AnomalyTimelineResponse } from "@/types";

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

function toneColor(tone: string) {
  if (tone === "red") return "var(--red)";
  if (tone === "orange") return "var(--orange)";
  if (tone === "accent") return "var(--accent-600)";
  return "var(--muted)";
}

export function DashboardPage() {
  // API data
  const [overview, setOverview] = useState<AnomalyOverview | null>(null);
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

  // Alert drawer / KPI
  const [openKpi, setOpenKpi] = useState<string | null>(null);
  const [buildingSort, setBuildingSort] = useState<"critical" | "total">("critical");

  const router = useRouter();

  // On-mount fetch (3 parallel)
  useEffect(() => {
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoadingDash(true);
    Promise.all([
      getAnomalyOverview({ ...SIMULATION_RANGE_QUERY }, controller.signal),
      getAnomalyEvents({ sort: "oldest", ...SIMULATION_RANGE_QUERY }, controller.signal),
      getAnomalyFacets(undefined, controller.signal),
    ])
      .then(([ov, evs, fcts]) => {
        setOverview(ov);
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

  // Top 3 buildings by critical anomaly count at simNow.
  const topCriticalBuildings = useMemo(() => {
    const byBuilding = new Map<string, { count: number; latestEvent: AnomalyEvent }>();
    visibleDashboardEvents
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
  }, [visibleDashboardEvents]);

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
        return { buildingId, status, totalCount: events.length, criticalCount };
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

  // KPI strip — override anomaly counts from real API
  const kpis = useMemo(() => {
    if (!overview) return KPIS;
    return KPIS.map((kpi) => {
      if (kpi.key === "anom" || kpi.label?.toLowerCase().includes("anomal")) {
        return { ...kpi, value: String(overview.total_anomalies) };
      }
      if (kpi.key === "crit" || kpi.label?.toLowerCase().includes("critical")) {
        return { ...kpi, value: String(overview.critical_anomalies) };
      }
      return kpi;
    });
  }, [overview]);

  // Severity items update with the global simulation cursor.
  const severityItems = useMemo(() => {
    const counts = { Critical: 0, High: 0, Medium: 0, Low: 0 };
    visibleDashboardEvents.forEach((event) => {
      if (event.severity in counts) counts[event.severity as keyof typeof counts] += 1;
    });
    return [
      { key: "critical", label: "Critical", value: counts.Critical ?? 0, tone: "red" },
      { key: "high",     label: "High",     value: counts.High ?? 0,     tone: "orange" },
      { key: "medium",   label: "Medium",   value: counts.Medium ?? 0,   tone: "accent" },
      { key: "low",      label: "Low",      value: counts.Low ?? 0,      tone: "accent" },
    ] as const;
  }, [visibleDashboardEvents]);

  return (
    <div className="page">
      <div className="page-head">
      </div>


      <div className="grid kpi-summary">
        {kpis.map((kpi, index) => (
          <KpiCard
            key={kpi.key}
            kpi={kpi}
            open={openKpi === kpi.key}
            onToggle={() => setOpenKpi((current) => (current === kpi.key ? null : kpi.key))}
            onClose={() => setOpenKpi(null)}
            windowAlign={index >= kpis.length - 2 ? "end" : "start"}
          />
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
            <div style={{ height: 296 }} />
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
            <Link href="/anomaly" className="btn btn-sm">
              View all <Icon name="arrowRight" />
            </Link>
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
            {topCriticalBuildings.map(({ buildingId, count, latestEvent }) => (
              <div key={buildingId} className="anom-needs-row">
                <span className="badge badge-critical"><i className="bdot" />critical</span>
                <span className="anom-needs-info">
                  <b>{displayLocationName(null, buildingId)}</b>
                  <small>{count} critical anomal{count === 1 ? "y" : "ies"}</small>
                </span>
                <span className="mono anom-needs-time">{timeAgo(new Date(latestEvent.start_time).getTime())}</span>
              </div>
            ))}
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
                ).slice(0, 8).map((event) => (
                  <tr key={event.id} onClick={() => router.push(`/anomaly?building=${event.building_id}&site=${event.site_id}`)}>
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
                ))}
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
            {buildingStatusRows.map((row) => (
              <div key={row.buildingId} className="site-status-row">
                <div className="site-status-info">
                  <b>{displayLocationName(null, row.buildingId)}</b>
                  <small>{row.criticalCount > 0 ? `${row.criticalCount} critical` : "No critical"}</small>
                </div>
                <span className="mono" style={{ fontSize: 12, color: "var(--muted)", marginLeft: "auto" }}>
                  {row.totalCount} open
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
