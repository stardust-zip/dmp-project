"use client";

import { useEffect, useMemo, useState } from "react";
import { EChart } from "@/components/common/charts";
import { Icon } from "@/components/common/icons";
import { Card, Field, Select, Spinner } from "@/components/common/primitives";
import { fmt } from "@/lib/format";
import { getLocationOptions, getMetricOptions, type LocationOption, type MetricOption } from "@/lib/models-api";
import {
  getExpectedVsActual,
  predictScenario,
  type ExpectedActualResponse,
  type PredictionScenarioResponse,
} from "@/lib/prediction-api";

type PredictionTab = "scenario" | "report";

const DEFAULT_SITE = "Panther";
const DEFAULT_BUILDING = "Panther_parking_Lorriane";
const DEFAULT_METRIC = "electricity";

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

function isoDate(value: string, endOfDay = false) {
  return `${value}T${endOfDay ? "23:59:59" : "00:00:00"}Z`;
}

function money(value?: number | null) {
  if (value == null) return "-";
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(value);
}

function wholeHour(value: string) {
  return value.length === 5 ? value : `${value}:00`;
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
  const [tab, setTab] = useState<PredictionTab>("scenario");
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [metrics, setMetrics] = useState<MetricOption[]>([]);
  const [siteId, setSiteId] = useState(DEFAULT_SITE);
  const [buildingId, setBuildingId] = useState(DEFAULT_BUILDING);
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
        getLocationOptions({ limit: 100 }, controller.signal),
        getMetricOptions(controller.signal),
      ]);
      setLocations(locationData.locations);
      setMetrics(metricData.metrics);
    }
    void loadOptions().catch(() => undefined);
    return () => controller.abort();
  }, []);

  const siteOptions = useMemo(
    () => [
      { value: DEFAULT_SITE, label: DEFAULT_SITE },
      ...locations
        .filter((location) => location.location_type === "site")
        .map((location) => ({ value: location.id, label: location.name || location.id })),
    ],
    [locations],
  );

  const buildingOptions = useMemo(
    () => [
      { value: DEFAULT_BUILDING, label: DEFAULT_BUILDING },
      ...locations
        .filter((location) => location.location_type !== "site")
        .map((location) => ({ value: location.id, label: location.name || location.id })),
    ],
    [locations],
  );

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

  async function runScenario() {
    setLoading(true);
    setError(null);
    try {
      setScenario(
        await predictScenario({
          site_id: siteId,
          building_id: buildingId,
          metric_type: metricType,
          scenario_date: isoDate(scenarioDate),
          opening_time: wholeHour(openingTime),
          closing_time: wholeHour(closingTime),
          unit_rate: rate ? Number(rate) : null,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scenario prediction failed.");
    } finally {
      setLoading(false);
    }
  }

  async function runReport() {
    setLoading(true);
    setError(null);
    try {
      setReport(
        await getExpectedVsActual({
          site_id: siteId,
          building_id: buildingId,
          metric_type: metricType,
          start_time: isoDate(reportStart),
          end_time: isoDate(reportEnd, true),
          opening_time: wholeHour(openingTime),
          closing_time: wholeHour(closingTime),
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Report generation failed.");
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

      <Card title="Prediction Inputs" icon="target" sub="Building, operating hours, and metric selection" style={{ marginBottom: "var(--gap)" }}>
        <div className="grid" style={{ gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 12 }}>
          <Field label="Site">
            <Select value={siteId} onChange={setSiteId} options={siteOptions} searchable />
          </Field>
          <Field label="Building">
            <Select value={buildingId} onChange={setBuildingId} options={buildingOptions} searchable />
          </Field>
          <Field label="Metric">
            <Select value={metricType} onChange={setMetricType} options={metricOptions} searchable />
          </Field>
          <Field label="Closing Time">
            <input className="input" type="time" step="3600" value={closingTime} onChange={(event) => setClosingTime(event.target.value)} />
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
              <Field label={`Unit Rate ($/${selectedMetricUnit})`}>
                <input className="input" type="number" min="0" step="0.01" value={rate} onChange={(event) => setRate(event.target.value)} />
              </Field>
              <button className="btn btn-primary" onClick={runScenario} disabled={loading}>
                {loading ? <Spinner size={14} /> : <Icon name="play" />} Predict Cost
              </button>
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
              <Field label="Opening Time">
                <input className="input" type="time" step="3600" value={openingTime} onChange={(event) => setOpeningTime(event.target.value)} />
              </Field>
              <button className="btn btn-primary" onClick={runReport} disabled={loading}>
                {loading ? <Spinner size={14} /> : <Icon name="play" />} Generate Report
              </button>
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

      {error && (
        <div className="training-validation is-invalid" style={{ marginTop: "var(--gap)" }}>
          <Icon name="alert" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
