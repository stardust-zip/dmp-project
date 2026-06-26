import type {
  Alert,
  AlertStatus,
  AnomalySummary,
  Building,
  BuildingConsumption,
  CauseAction,
  ForecastKpi,
  ForecastPoint,
  ForecastTailPoint,
  HealthBuilding,
  Kpi,
  ModelPerf,
  SeriesPoint,
  Severity,
} from "@/types";

export function mulberry32(a: number) {
  return function random() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const SITES = ["North Campus", "South Campus", "Riverside Park", "Harbor District"];

export const BUILDINGS: Building[] = [
  { id: "B-01", name: "HQ Tower A", site: "North Campus", base: 1820, area: 142000 },
  { id: "B-02", name: "Research Lab West", site: "North Campus", base: 1560, area: 98000 },
  { id: "B-03", name: "Logistics Center", site: "South Campus", base: 1340, area: 210000 },
  { id: "B-04", name: "Data Hall 2", site: "South Campus", base: 2240, area: 64000 },
  { id: "B-05", name: "Manufacturing Unit", site: "Riverside Park", base: 1980, area: 188000 },
  { id: "B-06", name: "Office Block C", site: "North Campus", base: 1120, area: 76000 },
  { id: "B-07", name: "Cold Storage", site: "Harbor District", base: 1690, area: 54000 },
  { id: "B-08", name: "Admin Building", site: "Riverside Park", base: 740, area: 41000 },
  { id: "B-09", name: "Distribution Hub", site: "Harbor District", base: 1410, area: 156000 },
  { id: "B-10", name: "Training Facility", site: "South Campus", base: 560, area: 33000 },
];

function loadShape(hour: number) {
  const points = [
    0.55, 0.5, 0.48, 0.47, 0.49, 0.55, 0.7, 0.86, 0.98, 1.02, 1.05, 1.07,
    1.06, 1.08, 1.12, 1.13, 1.08, 0.98, 0.88, 0.8, 0.74, 0.68, 0.62, 0.58,
  ];
  return points[hour % 24];
}

export function buildSeries({
  points,
  stepHours,
  baseHourly,
  seed,
  noise = 0.05,
  anomalies = [],
}: {
  points: number;
  stepHours: number;
  baseHourly: number;
  seed: number;
  noise?: number;
  anomalies?: Array<{ ago: number; mult: number; sev: Severity }>;
}) {
  const random = mulberry32(seed);
  const now = Date.now();
  const series: SeriesPoint[] = [];

  for (let i = points - 1; i >= 0; i -= 1) {
    const t = now - i * stepHours * 3600 * 1000;
    const date = new Date(t);
    const weekend = date.getDay() === 0 || date.getDay() === 6 ? 0.78 : 1;
    const expected = baseHourly * loadShape(date.getHours()) * stepHours * weekend;
    const actual = expected * (1 + (random() - 0.5) * 2 * noise);
    series.push({ t, expected: Math.round(expected), actual: Math.round(actual) });
  }

  anomalies.forEach((anomaly) => {
    const index = series.length - 1 - anomaly.ago;
    if (series[index]) {
      series[index].actual = Math.round(series[index].expected * anomaly.mult);
      series[index].anomaly = anomaly.sev;
    }
  });

  return series;
}

export const TREND: Record<string, SeriesPoint[]> = {
  "24h": buildSeries({ points: 48, stepHours: 0.5, baseHourly: 520, seed: 11, noise: 0.04 }),
  "7d": buildSeries({ points: 84, stepHours: 2, baseHourly: 525, seed: 22, noise: 0.05 }),
  "30d": buildSeries({ points: 90, stepHours: 8, baseHourly: 528, seed: 33, noise: 0.06 }),
};

function withForecast(series: SeriesPoint[], fcPoints: number, stepHours: number, seed: number) {
  const random = mulberry32(seed);
  const last = series[series.length - 1];
  const forecast: ForecastTailPoint[] = [];

  for (let i = 1; i <= fcPoints; i += 1) {
    const t = last.t + i * stepHours * 3600 * 1000;
    const date = new Date(t);
    const expected =
      525 * loadShape(date.getHours()) * stepHours * (date.getDay() === 0 || date.getDay() === 6 ? 0.78 : 1);
    forecast.push({ t, forecast: Math.round(expected * (1 + (random() - 0.5) * 0.04)) });
  }

  return forecast;
}

export const TREND_FC: Record<string, ForecastTailPoint[]> = {
  "24h": withForecast(TREND["24h"], 16, 0.5, 101),
  "7d": withForecast(TREND["7d"], 18, 2, 202),
  "30d": withForecast(TREND["30d"], 15, 8, 303),
};

export const BY_BUILDING: BuildingConsumption[] = BUILDINGS.map((building, index) => {
  const random = mulberry32(700 + index);
  return { ...building, kwh: Math.round(building.base * 6.9 * (0.9 + random() * 0.25)) };
}).sort((a, b) => b.kwh - a.kwh);

const HEALTH_RULES = [
  { id: "B-04", status: "red", consumption: 14820, note: "Sustained overload" },
  { id: "B-05", status: "yellow", consumption: 13110, note: "Above baseline" },
  { id: "B-07", status: "yellow", consumption: 11240, note: "Cooling spike" },
  { id: "B-01", status: "green", consumption: 12180, note: "Nominal" },
] as const;

export const HEALTH: HealthBuilding[] = BUILDINGS.map((building, index) => {
  const rule = HEALTH_RULES.find((entry) => entry.id === building.id);
  const random = mulberry32(900 + index);
  const found = BY_BUILDING.find((entry) => entry.id === building.id);
  return {
    ...building,
    status: rule?.status ?? "green",
    note: rule?.note ?? "Nominal",
    consumption: rule?.consumption ?? found?.kwh ?? 0,
    load: rule ? (rule.status === "red" ? 0.94 : rule.status === "yellow" ? 0.81 : 0.58) : 0.4 + random() * 0.25,
  };
});

export const ALERT_TYPES = [
  "Consumption Spike",
  "Baseline Deviation",
  "Missing Data",
  "Meter Offline",
  "Off-Schedule Load",
  "Demand Surge",
  "Phase Imbalance",
];

export const STATUSES: AlertStatus[] = ["Open", "Acknowledged", "Resolved"];

export function genAlerts(n: number, seed: number) {
  const random = mulberry32(seed);
  const alerts: Alert[] = [];

  for (let i = 0; i < n; i += 1) {
    const building = BUILDINGS[Math.floor(random() * BUILDINGS.length)];
    const type = ALERT_TYPES[Math.floor(random() * ALERT_TYPES.length)];
    const severityRoll = random();
    const sev: Severity = severityRoll > 0.82 ? "critical" : severityRoll > 0.5 ? "warning" : "info";
    const expected = Math.round(building.base * (0.9 + random() * 0.6) * 7);
    const dev =
      type === "Missing Data"
        ? null
        : sev === "critical"
          ? 18 + random() * 52
          : sev === "warning"
            ? 8 + random() * 14
            : -6 - random() * 8;
    const actual = dev == null ? null : Math.round(expected * (1 + dev / 100));
    const ago = Math.floor(random() * 60 * 26) * 60 * 1000 + Math.floor(random() * 3600000);
    const status = sev === "info" ? (random() > 0.4 ? "Resolved" : "Acknowledged") : STATUSES[Math.floor(random() * 3)];

    alerts.push({
      id: `ANM-${4820 + i}`,
      ts: Date.now() - ago,
      building,
      meter: `MTR-${building.id.slice(2)}-${String.fromCharCode(65 + (i % 4))}${10 + (i % 7)}`,
      type,
      sev,
      status,
      actual,
      expected,
      dev,
    });
  }

  return alerts.sort((a, b) => b.ts - a.ts);
}

export const ALERTS_ALL = genAlerts(54, 4242);
export const ALERTS_RECENT = ALERTS_ALL.slice(0, 7);

export function spark(seed: number, up: boolean) {
  const random = mulberry32(seed);
  const values: number[] = [];
  let value = 50;
  for (let i = 0; i < 22; i += 1) {
    value += (random() - (up ? 0.42 : 0.58)) * 14;
    value = Math.max(8, Math.min(92, value));
    values.push(Math.round(value));
  }
  return values;
}

export const KPIS: Kpi[] = [
  { key: "current", label: "Current Consumption", value: "-", unit: "kWh", icon: "gauge", tone: "accent", delta: 0, deltaLabel: "vs expected", spark: spark(4, true) },
  { key: "today", label: "Avg. Consumption - Today", value: "-", unit: "kWh", icon: "bolt", tone: "accent", delta: 0, deltaLabel: "vs yesterday", spark: spark(1, true) },
  { key: "yest", label: "Avg. Consumption - Yesterday", value: "-", unit: "kWh", icon: "calendar", tone: "slate", delta: 0, deltaLabel: "vs 2 days ago", spark: spark(2, false) },
  { key: "forecast", label: "Avg. Forecast - Next 6h", value: "-", unit: "kWh", icon: "trend", tone: "violet", delta: 0, deltaLabel: "projected", spark: spark(3, true) },
  { key: "crit", label: "Critical Alerts Today", value: "-", unit: "", icon: "alert", tone: "red", delta: 0, deltaLabel: "needs action", isCount: true, spark: spark(5, true) },
];

export const ANOMALY_SERIES = buildSeries({
  points: 96,
  stepHours: 1,
  baseHourly: 540,
  seed: 555,
  noise: 0.045,
  anomalies: [
    { ago: 6, mult: 1.62, sev: "critical" },
    { ago: 18, mult: 1.44, sev: "warning" },
    { ago: 31, mult: 1.78, sev: "critical" },
    { ago: 49, mult: 0.18, sev: "critical" },
    { ago: 67, mult: 1.39, sev: "warning" },
    { ago: 80, mult: 1.55, sev: "critical" },
  ],
});

export const ANOMALY_SUMMARY: AnomalySummary[] = [
  { key: "crit", label: "Critical Anomalies", value: 9, icon: "alert", tone: "red", delta: 2, sub: "Requires immediate review" },
  { key: "warn", label: "Warning Anomalies", value: 23, icon: "pulse", tone: "orange", delta: 5, sub: "Under threshold tuning" },
  { key: "missing", label: "Missing Data Events", value: 4, icon: "unplug", tone: "slate", delta: -1, sub: "Meter / gateway dropouts" },
  { key: "total", label: "Total Anomalies", value: 54, icon: "layers", tone: "accent", delta: 6, sub: "Across all sites - 7d" },
];

function buildForecastHistory() {
  const random = mulberry32(909);
  const history: Array<{ t: number; actual: number }> = [];
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  for (let i = 30; i >= 1; i -= 1) {
    const date = new Date(now.getTime() - i * 86400000);
    const weekend = date.getDay() === 0 || date.getDay() === 6 ? 0.8 : 1;
    const value = Math.round(12600 * weekend * (1 + (random() - 0.5) * 0.12) + i * 8);
    history.push({ t: date.getTime(), actual: value });
  }
  return history;
}

export const FC_HISTORY = buildForecastHistory();

function buildForecast(horizonDays: number, seed: number) {
  const random = mulberry32(seed);
  const last = FC_HISTORY[FC_HISTORY.length - 1];
  const start = new Date(last.t);
  const rows: ForecastPoint[] = [];

  for (let i = 1; i <= horizonDays; i += 1) {
    const date = new Date(start.getTime() + i * 86400000);
    const weekend = date.getDay() === 0 || date.getDay() === 6 ? 0.8 : 1;
    const yhat = Math.round(12750 * weekend * (1 + (random() - 0.5) * 0.05) + i * 6);
    const spread = Math.round(yhat * (0.035 + i * 0.0015));
    rows.push({ t: date.getTime(), yhat, lower: yhat - spread, upper: yhat + spread });
  }

  return rows;
}

export const FORECAST: Record<"day" | "week" | "month", ForecastPoint[]> = {
  day: buildForecast(1, 71),
  week: buildForecast(7, 72),
  month: buildForecast(30, 73),
};

export const FC_KPIS: ForecastKpi[] = [
  { key: "tom", label: "Predicted - Tomorrow", value: "13,200", unit: "kWh", icon: "trend", tone: "accent", delta: 5.3, sub: "95% CI +/- 520 kWh" },
  { key: "week", label: "Predicted - This Week", value: "89,440", unit: "kWh", icon: "calendar", tone: "violet", delta: 2.8, sub: "7-day rolling sum" },
  { key: "mape", label: "Forecast Accuracy (MAPE)", value: "3.4", unit: "%", icon: "target", tone: "green", delta: -0.6, sub: "Lower is better", invertGood: true },
  { key: "model", label: "Model Version", value: "v2.4.1", unit: "", icon: "cpu", tone: "slate", text: "TFT - retrained 2d ago", sub: "Temporal Fusion Transformer" },
];

export const MODEL_PERF: ModelPerf[] = [
  { key: "mae", label: "MAE", value: "412", unit: "kWh", desc: "Mean Absolute Error", delta: -3.1, tone: "accent" },
  { key: "rmse", label: "RMSE", value: "598", unit: "kWh", desc: "Root Mean Squared Error", delta: -2.4, tone: "violet" },
  { key: "mape", label: "MAPE", value: "3.4", unit: "%", desc: "Mean Abs. % Error", delta: -0.6, tone: "green" },
];

function perfTrend(seed: number, start: number, drift: number) {
  const random = mulberry32(seed);
  const values: number[] = [];
  let value = start;
  for (let i = 0; i < 14; i += 1) {
    value += (random() - 0.5) * start * 0.06 - drift;
    values.push(Math.max(1, Number(value.toFixed(1))));
  }
  return values;
}

export const PERF_TREND: Record<ModelPerf["key"], number[]> = {
  mae: perfTrend(41, 470, 4),
  rmse: perfTrend(42, 660, 4.5),
  mape: perfTrend(43, 4.2, 0.06),
};

export const CAUSE_LIB: Record<string, CauseAction[]> = {
  "Consumption Spike": [
    { t: "HVAC running outside schedule", d: "Cooling load active during unoccupied hours", ic: "snow", tone: "orange" },
    { t: "Unexpected occupancy", d: "Badge-in events exceed planned headcount", ic: "users", tone: "accent" },
    { t: "Equipment malfunction", d: "A sub-meter reports continuous peak draw", ic: "alert", tone: "red" },
  ],
  "Baseline Deviation": [
    { t: "Schedule drift", d: "Operating hours shifted from configured baseline", ic: "clock", tone: "orange" },
    { t: "Seasonal load change", d: "Ambient temperature outside model window", ic: "snow", tone: "accent" },
  ],
  "Missing Data": [
    { t: "Sensor / meter issue", d: "Gateway lost connection to the meter", ic: "unplug", tone: "slate" },
    { t: "Network outage", d: "Site telemetry gap detected", ic: "wifi", tone: "orange" },
  ],
  "Meter Offline": [{ t: "Sensor / meter issue", d: "Device unreachable for >30 min", ic: "unplug", tone: "red" }],
  "Off-Schedule Load": [
    { t: "HVAC running outside schedule", d: "Setpoints not following occupancy plan", ic: "snow", tone: "orange" },
    { t: "Equipment malfunction", d: "Process equipment failed to power down", ic: "alert", tone: "red" },
  ],
  "Demand Surge": [
    { t: "Unexpected occupancy", d: "Event or shift overlap increased demand", ic: "users", tone: "accent" },
    { t: "Equipment malfunction", d: "Simultaneous startup of major loads", ic: "alert", tone: "red" },
  ],
  "Phase Imbalance": [
    { t: "Equipment malfunction", d: "Load distribution skewed across phases", ic: "alert", tone: "red" },
    { t: "Sensor / meter issue", d: "CT calibration may be off", ic: "unplug", tone: "slate" },
  ],
};

export const ACTION_LIB: CauseAction[] = [
  { t: "Inspect equipment on-site", d: "Dispatch facilities to verify HVAC and major loads", ic: "wrench" },
  { t: "Verify meter health", d: "Check gateway connectivity and CT calibration", ic: "gauge" },
  { t: "Review operating schedule", d: "Confirm setpoints match occupancy plan", ic: "clock" },
];

export function causesFor(type: string) {
  return CAUSE_LIB[type] ?? CAUSE_LIB["Baseline Deviation"];
}
