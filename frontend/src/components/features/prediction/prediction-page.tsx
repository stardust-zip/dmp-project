"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { EChart } from "@/components/common/charts";
import { Icon } from "@/components/common/icons";
import { Card, Field, Select, Spinner } from "@/components/common/primitives";
import { displayLocationName, fmt, humanizeIdentifier, isSiteLocation } from "@/lib/format";
import { getLocationOptions, getMetricOptions, type LocationOption, type MetricOption } from "@/lib/models-api";
import {
  getExpectedVsActual,
  predictScenario,
  type ExpectedActualResponse,
  type PredictionScenarioResponse,
} from "@/lib/prediction-api";

type PredictionTab = "scenario" | "report";

const DEFAULT_BUILDING = "Panther_parking_Lorriane";
const DEFAULT_METRIC = "electricity";
const LOCATION_SEARCH_LIMIT = 40;

function tomorrowDate() {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  return date.toISOString().slice(0, 10);
}

function monthStartDate() {
  const date = new Date();
  date.setUTCDate(1);
  return date.toISOString().slice(0, 10);
}

function todayDate() {
  return new Date().toISOString().slice(0, 10);
}

function localDateTimeWithOffset(dateValue: string, timeValue: string) {
  const [hours, minutes] = wholeHour(timeValue).split(":").map(Number);
  const date = new Date(`${dateValue}T00:00:00`);
  date.setHours(hours, minutes, 0, 0);

  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absOffset = Math.abs(offsetMinutes);
  const offsetHours = String(Math.floor(absOffset / 60)).padStart(2, "0");
  const offsetRemainder = String(absOffset % 60).padStart(2, "0");
  const pad = (value: number) => String(value).padStart(2, "0");

  return `${dateValue}T${pad(hours)}:${pad(minutes)}:00${sign}${offsetHours}:${offsetRemainder}`;
}

function money(value?: number | null) {
  if (value == null) return "-";
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(value);
}

function wholeHour(value: string) {
  return value.length === 5 ? value : `${value}:00`;
}

function locationSubtitle(location: LocationOption, parent?: LocationOption | null) {
  const parts = [
    location.location_type ? humanizeIdentifier(location.location_type) : null,
    parent ? `Site: ${displayLocationName(parent.name, parent.id)}` : location.parent_id ? `Site: ${location.parent_id}` : null,
    location.id,
  ].filter(Boolean);
  return parts.join(" · ");
}

function buildExpectedActualChart(report: ExpectedActualResponse | null) {
  return (theme: { muted: string; grid: string; accent: string }) => {
    const points = report?.points ?? [];
    return {
      tooltip: { trigger: "axis" },
      grid: { top: 24, right: 18, bottom: 34, left: 54 },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: theme.grid } },
        axisLabel: { color: theme.muted },
      },
      yAxis: {
        type: "value",
        name: report?.unit ?? "units",
        nameTextStyle: { color: theme.muted },
        splitLine: { lineStyle: { color: theme.grid } },
        axisLabel: { color: theme.muted },
      },
      series: [
        {
          name: "Expected Usage",
          type: "line",
          smooth: 0.25,
          showSymbol: false,
          data: points.map((point) => [point.timestamp, point.expected_value]),
          lineStyle: { width: 1.6, color: theme.muted, type: [5, 4] },
        },
        {
          name: "Actual Usage",
          type: "line",
          smooth: 0.25,
          showSymbol: false,
          data: points.map((point) => [point.timestamp, point.actual_value ?? null]),
          lineStyle: { width: 2, color: theme.accent },
          areaStyle: { color: "rgba(37,99,235,.08)" },
        },
      ],
    };
  };
}

function ResultMetric({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="kpi">
      <div className="kpi-top">
        <span className="kpi-label">{label}</span>
        <span className="kpi-ic">
          <Icon name="bolt" />
        </span>
      </div>
      <div className="row" style={{ alignItems: "baseline", gap: 0 }}>
        <span className="kpi-val">{value}</span>
        {unit && <span className="kpi-unit">{unit}</span>}
      </div>
    </div>
  );
}

export function PredictionPage() {
  const locationPickerRef = useRef<HTMLDivElement | null>(null);
  const [tab, setTab] = useState<PredictionTab>("scenario");
  const [locationResults, setLocationResults] = useState<LocationOption[]>([]);
  const [metrics, setMetrics] = useState<MetricOption[]>([]);
  const [locationId, setLocationId] = useState(DEFAULT_BUILDING);
  const [selectedLocation, setSelectedLocation] = useState<LocationOption | null>(null);
  const [locationQuery, setLocationQuery] = useState(DEFAULT_BUILDING);
  const [locationPickerOpen, setLocationPickerOpen] = useState(false);
  const [locationSearchLoading, setLocationSearchLoading] = useState(false);
  const [metricType, setMetricType] = useState(DEFAULT_METRIC);
  const [scenarioDate, setScenarioDate] = useState(tomorrowDate);
  const [openingTime, setOpeningTime] = useState("06:00");
  const [closingTime, setClosingTime] = useState("22:00");
  const [rate, setRate] = useState("0.14");
  const [reportStart, setReportStart] = useState(monthStartDate);
  const [reportEnd, setReportEnd] = useState(todayDate);
  const [scenario, setScenario] = useState<PredictionScenarioResponse | null>(null);
  const [report, setReport] = useState<ExpectedActualResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function loadOptions() {
      const [locationData, metricData] = await Promise.all([
        getLocationOptions({ limit: 1000 }, controller.signal),
        getMetricOptions(controller.signal),
      ]);
      setLocationResults(locationData.locations.slice(0, LOCATION_SEARCH_LIMIT));
      setSelectedLocation(locationData.locations.find((location) => location.id === DEFAULT_BUILDING) ?? null);
      setMetrics(metricData.metrics);
    }
    void loadOptions().catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const closeIfOutside = (event: PointerEvent) => {
      if (!locationPickerRef.current?.contains(event.target as Node)) {
        setLocationPickerOpen(false);
      }
    };

    document.addEventListener("pointerdown", closeIfOutside);
    return () => document.removeEventListener("pointerdown", closeIfOutside);
  }, []);

  useEffect(() => {
    if (!locationPickerOpen) return;

    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      const query = locationQuery.trim();
      setLocationSearchLoading(true);
      try {
        const data = await getLocationOptions({ q: query || undefined, limit: 1000 }, controller.signal);
        setLocationResults(data.locations.slice(0, LOCATION_SEARCH_LIMIT));
      } catch {
        if (!controller.signal.aborted) setLocationResults([]);
      } finally {
        if (!controller.signal.aborted) setLocationSearchLoading(false);
      }
    }, locationQuery.trim() ? 180 : 0);

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [locationPickerOpen, locationQuery]);

  const locationById = useMemo(() => {
    return new Map(locationResults.map((location) => [location.id, location]));
  }, [locationResults]);

  const metricOptions = useMemo(
    () => [
      { value: DEFAULT_METRIC, label: DEFAULT_METRIC },
      ...metrics.filter((metric) => metric.id !== DEFAULT_METRIC).map((metric) => ({ value: metric.id, label: metric.id })),
    ],
    [metrics],
  );
  const selectedMetricUnit = useMemo(
    () => metrics.find((metric) => metric.id === metricType)?.unit || "units",
    [metricType, metrics],
  );

  function chooseLocation(location: LocationOption) {
    setLocationId(location.id);
    setSelectedLocation(location);
    setLocationQuery(displayLocationName(location.name, location.id));
    setLocationPickerOpen(false);
  }

  function predictionLocationPayload() {
    const selectedId = locationId.trim();
    if (!selectedId) return null;

    if (selectedLocation?.id === selectedId && selectedLocation.parent_id) {
      return {
        site_id: selectedLocation.parent_id,
        building_id: selectedLocation.id,
      };
    }

    if (selectedLocation?.id === selectedId && isSiteLocation(selectedLocation)) return null;

    const inferredSiteId = selectedId.includes("_") ? selectedId.split("_")[0] : selectedId;
    return {
      site_id: inferredSiteId,
      building_id: selectedId,
    };
  }

  async function runScenario() {
    const locationPayload = predictionLocationPayload();
    if (!locationPayload) {
      setError("Select a building location from the search results before running prediction.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      setScenario(
        await predictScenario({
          site_id: locationPayload.site_id,
          building_id: locationPayload.building_id,
          metric_type: metricType,
          scenario_date: localDateTimeWithOffset(scenarioDate, openingTime),
          opening_time: wholeHour(openingTime),
          closing_time: wholeHour(closingTime),
          unit_rate: rate ? Number(rate) : null,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? `Prediction failed: ${err.message}` : "Scenario prediction failed.");
    } finally {
      setLoading(false);
    }
  }

  async function runReport() {
    const locationPayload = predictionLocationPayload();
    if (!locationPayload) {
      setError("Select a building location from the search results before generating the report.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      setReport(
        await getExpectedVsActual({
          site_id: locationPayload.site_id,
          building_id: locationPayload.building_id,
          metric_type: metricType,
          start_time: localDateTimeWithOffset(reportStart, openingTime),
          end_time: localDateTimeWithOffset(reportEnd, closingTime),
          opening_time: wholeHour(openingTime),
          closing_time: wholeHour(closingTime),
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? `Report generation failed: ${err.message}` : "Report generation failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Prediction</h1>
          <p className="page-sub">Scenario planning and expected usage analysis</p>
        </div>
        <div className="seg">
          <button className={tab === "scenario" ? "on" : ""} onClick={() => setTab("scenario")}>Scenario Planner</button>
          <button className={tab === "report" ? "on" : ""} onClick={() => setTab("report")}>Monthly Report</button>
        </div>
      </div>

      <Card title="Prediction Inputs" icon="target" sub="Location and metric selection" style={{ marginBottom: "var(--gap)" }}>
        <div className="prediction-query-grid">
          <Field label="Location">
            <div className="prediction-combobox" ref={locationPickerRef}>
              <Icon name="search" />
              <input
                className="input"
                value={locationQuery}
                onFocus={() => setLocationPickerOpen(true)}
                onChange={(event) => {
                  setLocationQuery(event.target.value);
                  setLocationId("");
                  setSelectedLocation(null);
                  setLocationPickerOpen(true);
                }}
                placeholder="Search site or building by name or ID"
              />
              {locationPickerOpen && (
                <div className="prediction-picker-list">
                  {locationSearchLoading ? (
                    <div className="prediction-picker-empty">Searching locations...</div>
                  ) : locationResults.length ? (
                    locationResults.map((location) => (
                      <button key={location.id} type="button" onClick={() => chooseLocation(location)}>
                        <b>{displayLocationName(location.name, location.id)}</b>
                        <span>{locationSubtitle(location, location.parent_id ? locationById.get(location.parent_id) : null)}</span>
                      </button>
                    ))
                  ) : (
                    <div className="prediction-picker-empty">No locations found.</div>
                  )}
                </div>
              )}
            </div>
          </Field>
          <Field label="Metric">
            <Select value={metricType} onChange={setMetricType} options={metricOptions} searchable />
          </Field>
        </div>
      </Card>

      {tab === "scenario" ? (
        <div className="grid" style={{ gridTemplateColumns: "minmax(320px, .75fr) minmax(0, 1.25fr)" }}>
          <Card title="Scenario Planner" icon="sliders" sub="What-if operating load">
            <div className="grid" style={{ gap: 12 }}>
              <Field label="Date">
                <input className="input" type="date" value={scenarioDate} onChange={(event) => setScenarioDate(event.target.value)} />
              </Field>
              <Field label="Opening Time">
                <input className="input" type="time" step="3600" value={openingTime} onChange={(event) => setOpeningTime(event.target.value)} />
              </Field>
              <Field label="Closing Time">
                <input className="input" type="time" step="3600" value={closingTime} onChange={(event) => setClosingTime(event.target.value)} />
              </Field>
              <Field label={`Unit Rate ($/${selectedMetricUnit})`}>
                <input className="input" type="number" min="0" step="0.01" value={rate} onChange={(event) => setRate(event.target.value)} />
              </Field>
              <button className="btn btn-primary" onClick={runScenario} disabled={loading}>
                {loading ? <Spinner size={14} /> : <Icon name="play" />} Predict Cost
              </button>
              {error && (
                <div className="training-validation is-invalid" style={{ padding: "12px 14px" }}>
                  <Icon name="alert" />
                  <span>{error}</span>
                </div>
              )}
            </div>
          </Card>

          <div className="grid" style={{ gap: "var(--gap)" }}>
            <div className="grid" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
              <ResultMetric label="Estimated Usage" value={scenario ? fmt(scenario.estimated_value) : "-"} unit={scenario?.unit ?? selectedMetricUnit} />
              <ResultMetric label="Estimated Cost" value={money(scenario?.estimated_cost)} />
              <ResultMetric label="Model Version" value={scenario ? `v${scenario.model_version}` : "-"} />
            </div>
            <Card title="Hourly Estimate" icon="table" noBody>
              <div style={{ maxHeight: 360, overflow: "auto" }}>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Hour</th>
                      <th style={{ textAlign: "right" }}>Expected ({scenario?.unit ?? selectedMetricUnit})</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(scenario?.points ?? []).map((point) => (
                      <tr key={point.timestamp}>
                        <td>{new Date(point.timestamp).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</td>
                        <td className="mono" style={{ textAlign: "right" }}>{fmt(point.expected_value)}</td>
                      </tr>
                    ))}
                    {!scenario && (
                      <tr>
                        <td colSpan={2} style={{ color: "var(--muted)" }}>No scenario result</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        </div>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "minmax(320px, .75fr) minmax(0, 1.25fr)" }}>
          <Card title="Report Range" icon="calendar" sub="Expected usage against actual telemetry">
            <div className="grid" style={{ gap: 12 }}>
              <Field label="Start Date">
                <input className="input" type="date" value={reportStart} onChange={(event) => setReportStart(event.target.value)} />
              </Field>
              <Field label="End Date">
                <input className="input" type="date" value={reportEnd} onChange={(event) => setReportEnd(event.target.value)} />
              </Field>
              <button className="btn btn-primary" onClick={runReport} disabled={loading}>
                {loading ? <Spinner size={14} /> : <Icon name="play" />} Generate Report
              </button>
              {error && (
                <div className="training-validation is-invalid" style={{ padding: "12px 14px" }}>
                  <Icon name="alert" />
                  <span>{error}</span>
                </div>
              )}
            </div>
          </Card>

          <div className="grid" style={{ gap: "var(--gap)" }}>
            <div className="grid" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
              <ResultMetric label="Expected" value={report ? fmt(report.expected_total) : "-"} unit={report?.unit ?? selectedMetricUnit} />
              <ResultMetric label="Actual" value={report?.actual_total != null ? fmt(report.actual_total) : "-"} unit={report?.unit ?? selectedMetricUnit} />
              <ResultMetric label="Variance" value={report?.variance_total != null ? fmt(report.variance_total) : "-"} unit={report?.unit ?? selectedMetricUnit} />
            </div>
            <Card title="Expected vs. Actual" icon="trend" sub={report ? `${report.points.length} interval(s)` : "No report result"}>
              <EChart build={buildExpectedActualChart(report)} deps={[report]} themeKey={report?.model_version ?? "prediction"} height={340} />
            </Card>
          </div>
        </div>
      )}

    </div>
  );
}
