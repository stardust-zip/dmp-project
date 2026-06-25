"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { buildUnifiedAnomalyTimeline, EChart } from "@/components/common/charts";
import { SimulationControls, type SimBounds, type SpeedOption, MINUTE_MS } from "@/components/common/simulation-controls";
import { Icon } from "@/components/common/icons";
import { Card, KpiCard, Select, Spinner } from "@/components/common/primitives";
import { useAuth } from "@/components/auth/auth-provider";
import { getAnomalyOverview, getAnomalyEvents, getAnomalyFacets, getAnomalyTimeline } from "@/lib/anomaly-api";
import { displayLocationName, timeAgo } from "@/lib/format";
import { KPIS } from "@/lib/mock-data";
import type { AnomalyEvent, AnomalyFacets, AnomalyOverview, AnomalyTimelineResponse } from "@/types";

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;
const TICK_MS = 250;
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
  const [simBounds, setSimBounds] = useState<SimBounds | null>(null);
  const [simNow, setSimNow] = useState<number | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<SpeedOption>("6");

  // Loading / error
  const [loadingDash, setLoadingDash] = useState(true);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Alert drawer / KPI
  const [openKpi, setOpenKpi] = useState<string | null>(null);

  const { session } = useAuth();

  // On-mount fetch (3 parallel)
  useEffect(() => {
    const controller = new AbortController();
    setLoadingDash(true);
    Promise.all([
      getAnomalyOverview({ ...SIMULATION_RANGE_QUERY }, controller.signal),
      getAnomalyEvents({ sort: "newest", limit: 200, ...SIMULATION_RANGE_QUERY }, controller.signal),
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
      setRawTimeline(EMPTY_TIMELINE);
      setSimBounds(null);
      setSimNow(null);
      setIsPlaying(false);
      return;
    }
    const controller = new AbortController();
    setLoadingTimeline(true);
    setIsPlaying(false);
    getAnomalyTimeline(
      { building: selectedBuilding, limit: SIMULATION_FETCH_LIMIT, ...SIMULATION_RANGE_QUERY },
      controller.signal,
    )
      .then((tl) => {
        const bounds = timelineBounds(tl);
        setRawTimeline(tl);
        setSimBounds(bounds);
        setSimNow(bounds?.start ?? null);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingTimeline(false);
      });
    return () => controller.abort();
  }, [selectedBuilding]);

  // Playback tick
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

  // Derived values
  const visibleTimeline = useMemo(
    () => (simNow == null ? EMPTY_TIMELINE : timelineUntil(rawTimeline, simNow)),
    [rawTimeline, simNow],
  );
  const timelineZoom = useMemo(() => followZoomWindow(simBounds, simNow), [simBounds, simNow]);
  const shouldFollowTimeline = isPlaying && timelineZoom != null;

  // Fleet status
  const criticalCount = overview?.critical_anomalies ?? 0;
  const totalAnomalies = overview?.total_anomalies ?? 0;
  const fleetTone = criticalCount > 0 ? "red" : totalAnomalies > 0 ? "amber" : "green";

  // Top 3 critical from recentEvents
  const topCritical = useMemo(
    () => recentEvents.filter((e) => e.severity === "Critical").slice(0, 3),
    [recentEvents],
  );

  // Site status from recentEvents
  const siteStatusRows = useMemo(() => {
    const bysite = new Map<string, AnomalyEvent[]>();
    recentEvents.forEach((e) => {
      const arr = bysite.get(e.site_id) ?? [];
      arr.push(e);
      bysite.set(e.site_id, arr);
    });
    return [...bysite.entries()].map(([site, events]) => {
      const hasCritical = events.some((e) => e.severity === "Critical");
      const hasHigh = events.some((e) => e.severity === "High");
      const status = hasCritical ? "red" : hasHigh ? "yellow" : "green";
      const buildings = new Set(events.map((e) => e.building_id)).size;
      return { site, status, openCount: events.length, buildings };
    });
  }, [recentEvents]);

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

  // Severity items from real overview
  const severityItems = [
    { key: "critical", label: "Critical", value: overview?.severity_counts?.Critical ?? 0, tone: "red" },
    { key: "high", label: "High", value: overview?.severity_counts?.High ?? 0, tone: "orange" },
    { key: "medium", label: "Medium", value: overview?.severity_counts?.Medium ?? 0, tone: "accent" },
    { key: "low", label: "Low", value: overview?.severity_counts?.Low ?? 0, tone: "accent" },
  ] as const;

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

          <SimulationControls
            bounds={simBounds}
            simNow={simNow}
            isPlaying={isPlaying}
            speed={speed}
            disabled={loadingTimeline}
            onPlayToggle={() => {
              if (!simBounds || simNow == null) return;
              if (simNow >= simBounds.end) setSimNow(simBounds.start);
              setIsPlaying((c) => !c);
            }}
            onReset={() => {
              if (!simBounds) return;
              setSimNow(simBounds.start);
              setIsPlaying(false);
            }}
            onScrub={(v) => {
              if (!simBounds) return;
              setSimNow(Math.max(simBounds.start, Math.min(simBounds.end, v)));
              setIsPlaying(false);
            }}
            onSpeedChange={setSpeed}
          />

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
            {topCritical.length === 0 && !loadingDash && (
              <div className="empty" style={{ padding: "12px 0" }}>No critical alerts</div>
            )}
            {topCritical.map((event) => (
              <div key={event.id} className="anom-needs-row">
                <span className="badge badge-critical"><i className="bdot" />critical</span>
                <span className="anom-needs-info">
                  <b>{displayLocationName(null, event.building_id)}</b>
                  <small>{event.type}</small>
                </span>
                <span className="mono anom-needs-time">{timeAgo(new Date(event.start_time).getTime())}</span>
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
          actions={
            <Link className="btn btn-sm" href="/anomaly">
              View all <Icon name="arrowRight" />
            </Link>
          }
          noBody
        >
          <div className="table-scroll">
            <table className="tbl">
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
                {!loadingDash && recentEvents.length === 0 && (
                  <tr>
                    <td colSpan={5}><div className="empty">No recent alerts.</div></td>
                  </tr>
                )}
                {recentEvents.slice(0, 8).map((event) => (
                  <tr key={event.id}>
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
            <div style={{ display: "flex", gap: 10, fontSize: 11, color: "var(--muted)" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}><i className="status-dot s-green" /> Normal</span>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}><i className="status-dot s-yellow" /> Warning</span>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}><i className="status-dot s-red" /> Critical</span>
            </div>
          }
        >
          <div className="site-status-list">
            {loadingDash && <div className="empty"><Spinner /> Loading...</div>}
            {!loadingDash && siteStatusRows.length === 0 && (
              <div className="empty">No site data available.</div>
            )}
            {siteStatusRows.map((row) => {
              const dotClass = row.status === "red" ? "s-red" : row.status === "yellow" ? "s-yellow" : "s-green";
              const badgeTone = row.status === "red" ? "critical" : row.status === "yellow" ? "warning" : "resolved";
              return (
                <div key={row.site} className="site-status-row">
                  <i className={`status-dot ${dotClass}`} />
                  <div className="site-status-info">
                    <b>{row.site}</b>
                    <small>{row.buildings} building{row.buildings !== 1 ? "s" : ""}</small>
                  </div>
                  <span className={`badge badge-${badgeTone}`}>
                    <i className="bdot" />
                    {row.openCount > 0 ? `${row.openCount} open` : "No alerts"}
                  </span>
                  <Link href={`/anomaly?site=${row.site}`} className="btn btn-sm btn-ghost site-status-link">
                    <Icon name="arrowRight" />
                  </Link>
                </div>
              );
            })}
          </div>
        </Card>
      </div>
    </div>
  );
}
