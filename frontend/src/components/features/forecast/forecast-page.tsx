"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { buildForecastVsActualChart, EChart } from "@/components/common/charts";
import { Icon } from "@/components/common/icons";
import { Card, Field, Select, Spinner } from "@/components/common/primitives";
import { displayModelName, fmt } from "@/lib/format";
import { useAuth } from "@/components/auth/auth-provider";
import {
  getForecastAvailability,
  generateForecastVsActual,
  getForecastModelCoverage,
  getLocationOptions,
  getMetricOptions,
  type ForecastAvailabilityResponse,
  type ForecastVsActualResponse,
  type LocationOption,
  type MetricOption,
} from "@/lib/models-api";

const FORECAST_LENGTH_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "24", label: "1 day" },
  { value: "48", label: "2 days" },
  { value: "72", label: "3 days" },
  { value: "168", label: "7 days" },
];

const MIN_INPUT_DAYS = 14; // 168h lag warmup + up to 168h model horizon.

function defaultInputStart() {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() - 14);
  return date.toISOString().slice(0, 10);
}

function defaultInputEnd() {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

function toIsoUtc(date: string, endOfDay = false) {
  return `${date}T${endOfDay ? "23:59:59" : "00:00:00"}Z`;
}

function datePart(value?: string | null) {
  return value?.slice(0, 10) ?? null;
}

function optionLabel(options: Array<{ id?: string; value?: string; name?: string; label?: string }>, id: string) {
  const match = options.find((option) => (option.id ?? option.value) === id);
  return match?.name ?? match?.label ?? id;
}

export function ForecastPage() {
  const { session } = useAuth();
  const user = session?.user;

  const [sites, setSites] = useState<LocationOption[]>([]);
  const [buildings, setBuildings] = useState<LocationOption[]>([]);
  const [metrics, setMetrics] = useState<MetricOption[]>([]);
  const [droppedBuildingIds, setDroppedBuildingIds] = useState<string[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(true);

  const [siteId, setSiteId] = useState("");
  const [buildingId, setBuildingId] = useState("");
  const [metricType, setMetricType] = useState("electricity");
  const [inputStart, setInputStart] = useState(defaultInputStart());
  const [inputEnd, setInputEnd] = useState(defaultInputEnd());
  const [forecastHours, setForecastHours] = useState("48");

  const [result, setResult] = useState<ForecastVsActualResponse | null>(null);
  const [availability, setAvailability] = useState<ForecastAvailabilityResponse | null>(null);
  const [availabilityLoading, setAvailabilityLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load accessible sites + metrics once.
  useEffect(() => {
    const controller = new AbortController();
    setOptionsLoading(true);
    Promise.all([
      getLocationOptions({ locationType: "site" }, controller.signal),
      getMetricOptions(controller.signal),
    ])
      .then(([siteData, metricData]) => {
        setSites(siteData.locations);
        setMetrics(metricData.metrics);
        if (siteData.locations[0]) setSiteId(siteData.locations[0].id);
        if (metricData.metrics[0]) setMetricType(metricData.metrics[0].id);
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : "Unable to load forecast options.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setOptionsLoading(false);
      });
    // Fetch the production model's building coverage so dropped buildings can be
    // hidden from the dropdown. Non-fatal: no model yet -> show all buildings.
    getForecastModelCoverage(controller.signal)
      .then((coverage) => {
        if (!controller.signal.aborted) setDroppedBuildingIds(coverage.dropped_building_ids);
      })
      .catch(() => {
        /* No production forecasting model yet; keep droppedBuildingIds empty. */
      });
    return () => controller.abort();
  }, []);

  // Load buildings whenever the selected site changes.
  useEffect(() => {
    if (!siteId) {
      setBuildings([]);
      setBuildingId("");
      setAvailability(null);
      return;
    }
    const controller = new AbortController();
    getLocationOptions({ parentId: siteId }, controller.signal)
      .then((data) => {
        const childBuildings = data.locations.filter((location) => location.id !== siteId);
        setBuildings(childBuildings);
        setBuildingId(childBuildings[0]?.id ?? "");
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setBuildings([]);
          setBuildingId("");
          setError(err instanceof Error ? err.message : "Unable to load buildings for this site.");
        }
      });
    return () => controller.abort();
  }, [siteId]);

  // Buildings the production model can actually forecast = site's children minus
  // those dropped (>30% missing) during the latest training run.
  const visibleBuildings = useMemo(
    () => buildings.filter((building) => !droppedBuildingIds.includes(building.id)),
    [buildings, droppedBuildingIds],
  );
  const hiddenCount = buildings.length - visibleBuildings.length;

  // Keep the selected building inside the visible set once coverage arrives.
  useEffect(() => {
    if (!visibleBuildings.length) return;
    if (!visibleBuildings.some((building) => building.id === buildingId)) {
      setBuildingId(visibleBuildings[0].id);
    }
  }, [visibleBuildings, buildingId]);

  useEffect(() => {
    if (!buildingId || !metricType) {
      setAvailability(null);
      return;
    }

    const controller = new AbortController();
    setAvailabilityLoading(true);
    getForecastAvailability(buildingId, metricType, controller.signal)
      .then((data) => {
        setAvailability(data);
        if (data.recommended_input_start) {
          setInputStart(data.recommended_input_start.slice(0, 10));
        }
        if (data.recommended_input_end) {
          setInputEnd(data.recommended_input_end.slice(0, 10));
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setAvailability(null);
          setError(err instanceof Error ? err.message : "Unable to load telemetry availability.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setAvailabilityLoading(false);
      });

    return () => controller.abort();
  }, [buildingId, metricType]);

  const inputDays = useMemo(() => {
    if (!inputStart || !inputEnd) return 0;
    return Math.round((new Date(inputEnd).getTime() - new Date(inputStart).getTime()) / 86_400_000);
  }, [inputStart, inputEnd]);

  const canGenerate =
    !optionsLoading &&
    !availabilityLoading &&
    Boolean(buildingId && metricType && inputStart && inputEnd && inputDays >= MIN_INPUT_DAYS && (availability?.row_count ?? 0) > 0) &&
    !loading;

  const onGenerate = useCallback(async () => {
    if (!buildingId || !metricType) return;
    setLoading(true);
    setError(null);
    setResult(null);
    const recommendedStart = availability?.recommended_input_start;
    const recommendedEnd = availability?.recommended_input_end;
    const requestInputStart =
      recommendedStart && datePart(recommendedStart) === inputStart
        ? recommendedStart
        : toIsoUtc(inputStart);
    const requestInputEnd =
      recommendedEnd && datePart(recommendedEnd) === inputEnd
        ? recommendedEnd
        : toIsoUtc(inputEnd, true);
    try {
      const response = await generateForecastVsActual({
        building_id: buildingId,
        metric_type: metricType,
        input_start: requestInputStart,
        input_end: requestInputEnd,
        forecast_hours: Number(forecastHours),
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Forecast generation failed.");
    } finally {
      setLoading(false);
    }
  }, [availability, buildingId, metricType, inputStart, inputEnd, forecastHours]);

  const actualCount = result?.points.filter((point) => point.actual != null).length ?? 0;
  const forecastCount = result?.points.filter((point) => point.forecast != null).length ?? 0;
  const canSeeModelDetails = user?.role === "Admin" || user?.role === "AI_Engineer";

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Forecasting</h1>
          <p className="page-sub">Run the production forecasting model to predict future consumption for a building.</p>
        </div>
      </div>

      <Card
        title="Generate Forecast"
        icon="trend"
        iconTone="violet"
        sub="Pick a building, a window of recent actuals, and how far ahead to forecast."
        style={{ marginBottom: "var(--gap)" }}
      >
        <div className="train-model-form">
          <Field label="Site">
            <Select
              value={siteId}
              onChange={setSiteId}
              disabled={optionsLoading}
              options={sites.map((site) => ({ value: site.id, label: site.name || site.id }))}
            />
          </Field>
          <Field label="Building">
            <Select
              value={buildingId}
              onChange={setBuildingId}
              disabled={optionsLoading || !siteId}
              options={visibleBuildings.map((building) => ({ value: building.id, label: building.name || building.id }))}
            />
            {hiddenCount > 0 && (
              <span style={{ display: "block", color: "var(--muted)", fontSize: 12, marginTop: 8 }}>
                {hiddenCount} building(s) hidden — excluded from the production model's training data (&gt;30% missing).
              </span>
            )}
          </Field>
          <Field label="Metric">
            <Select
              value={metricType}
              onChange={setMetricType}
              options={metrics.map((metric) => ({ value: metric.id, label: metric.id }))}
            />
          </Field>
          <Field label="Input window (recent actuals)">
            <div className="date-range-row">
              <div className="date-range-segment">
                <Icon name="calendar" />
                <div className="date-range-segment-body">
                  <span>From</span>
                  <input type="date" value={inputStart} onChange={(event) => setInputStart(event.target.value)} />
                </div>
              </div>
              <div className="date-range-segment">
                <Icon name="calendar" />
                <div className="date-range-segment-body">
                  <span>To</span>
                  <input type="date" value={inputEnd} onChange={(event) => setInputEnd(event.target.value)} />
                </div>
              </div>
            </div>
            {availabilityLoading && (
              <span className="date-range-error">
                <Icon name="refresh" className="spin" />
                Checking telemetry coverage...
              </span>
            )}
            {!availabilityLoading && availability && availability.row_count > 0 && (
              <span style={{ display: "block", color: "var(--muted)", fontSize: 12, marginTop: 8 }}>
                Available {availability.first_timestamp?.slice(0, 10) ?? "unknown"} to {availability.last_timestamp?.slice(0, 10) ?? "unknown"} · {availability.row_count.toLocaleString()} rows.
              </span>
            )}
            {!availabilityLoading && availability && availability.row_count === 0 && (
              <span className="date-range-error">
                <Icon name="alert" />
                No telemetry exists for this building and metric.
              </span>
            )}
            {inputDays > 0 && inputDays < MIN_INPUT_DAYS && (
              <span className="date-range-error">
                <Icon name="alert" />
                At least {MIN_INPUT_DAYS} days of actuals are required ({inputDays} selected).
              </span>
            )}
          </Field>
          <Field label="Forecast length">
            <Select value={forecastHours} onChange={setForecastHours} options={FORECAST_LENGTH_OPTIONS} />
          </Field>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
          <button className="btn btn-primary" type="button" onClick={onGenerate} disabled={!canGenerate}>
            <Icon name={loading ? "refresh" : "play"} className={loading ? "spin" : undefined} />
            <span>{loading ? "Forecasting..." : "Generate Forecast"}</span>
          </button>
        </div>
        {user && (
          <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 8 }}>
            Signed in as <b>{user.roleLabel}</b>. Buildings are limited to your assigned sites.
          </div>
        )}
      </Card>

      {error && (
        <Card title="Forecast Error" icon="alert" style={{ marginBottom: "var(--gap)" }}>
          <div className="training-validation is-invalid">
            <Icon name="alert" />
            <span>{error}</span>
          </div>
          <div style={{ fontSize: 12, color: "var(--muted-2)", marginTop: 8 }}>
            If no production forecasting model exists yet, an AI Engineer must train one first from the Models page.
          </div>
        </Card>
      )}

      <Card
        title="Forecast vs Actual"
        icon="trend"
        iconTone="violet"
        sub={
          result
            ? `${optionLabel(buildings, result.building_id)} · ${result.metric_type} · horizon ${result.horizon_hours}h · forecasting ${result.forecast_hours}h ahead`
            : "Generate a forecast to see actual vs predicted consumption."
        }
        actions={
          result ? (
            <div className="legend">
              <span className="leg" style={{ color: "var(--accent-600)" }}><i style={{ background: "var(--accent-600)" }} /> Actual</span>
              <span className="leg" style={{ color: "#7c3aed" }}><i className="dash" style={{ color: "#7c3aed" }} /> Forecast</span>
            </div>
          ) : null
        }
        style={{ marginBottom: "var(--gap)" }}
      >
        {loading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: 48 }}>
            <Spinner size={22} />
          </div>
        ) : result ? (
          <>
            <EChart
              build={buildForecastVsActualChart(result.points, result.divider_timestamp)}
              deps={[result]}
              themeKey={`forecast-${result.building_id}`}
              height={340}
            />
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginTop: 12, fontSize: 12, color: "var(--muted)" }}>
              <span><b className="mono" style={{ color: "var(--ink-2)" }}>{actualCount}</b> actual points</span>
              <span><b className="mono" style={{ color: "var(--ink-2)" }}>{forecastCount}</b> forecast points</span>
              {canSeeModelDetails && result.model_name && (
                <span>model <b style={{ color: "var(--ink-2)" }}>{displayModelName(result.model_name)}</b></span>
              )}
              <span>run <b className="mono" style={{ color: "var(--ink-2)" }}>{result.model_run_id.slice(0, 8)}</b></span>
            </div>
          </>
        ) : (
          <div className="empty" style={{ padding: 48, textAlign: "center", color: "var(--muted-2)" }}>
            No forecast yet. Configure the inputs above and click <b>Generate Forecast</b>.
          </div>
        )}
      </Card>

      {result && result.points.some((point) => point.forecast != null) && (
        <Card title="Forecast Detail" icon="table" sub="Future hourly forecast values" noBody>
          <div className="table-scroll" style={{ maxHeight: 320 }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th style={{ textAlign: "right" }}>Forecast ({result.metric_type})</th>
                </tr>
              </thead>
              <tbody>
                {result.points
                  .filter((point) => point.forecast != null && new Date(point.timestamp).getTime() > new Date(result.divider_timestamp).getTime())
                  .map((point) => (
                    <tr key={point.timestamp}>
                      <td className="t-strong">
                        {new Date(point.timestamp).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
                      </td>
                      <td className="mono" style={{ textAlign: "right", fontWeight: 600 }}>{fmt(point.forecast ?? 0)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
