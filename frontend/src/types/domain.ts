export type Severity = "critical" | "warning" | "info";
export type AnomalySeverity = "Low" | "Medium" | "High" | "Critical";
export type AlertStatus = "Open" | "Acknowledged" | "Resolved";
export type BuildingStatus = "green" | "yellow" | "red";
export type Tone = "accent" | "slate" | "red" | "orange" | "green" | "violet" | "amber";
export type IconName =
  | "dot"
  | "grid"
  | "pulse"
  | "trend"
  | "bolt"
  | "calendar"
  | "alert"
  | "shield"
  | "search"
  | "bell"
  | "chevDown"
  | "chevRight"
  | "chevLeft"
  | "menu"
  | "panelLeft"
  | "settings"
  | "building"
  | "download"
  | "filter"
  | "refresh"
  | "x"
  | "cpu"
  | "target"
  | "layers"
  | "unplug"
  | "snow"
  | "users"
  | "clock"
  | "wrench"
  | "gauge"
  | "wifi"
  | "table"
  | "doc"
  | "excel"
  | "sliders"
  | "help"
  | "external"
  | "check"
  | "plus"
  | "play"
  | "pause"
  | "arrowUp"
  | "arrowDown"
  | "arrowRight"
  | "spark2"
  | "eye"
  | "map"
  | "flag"
  | "info";

export interface Building {
  id: string;
  name: string;
  site: string;
  base: number;
  area: number;
}

export interface SeriesPoint {
  t: number;
  expected: number;
  actual: number;
  anomaly?: Severity;
}

export interface ForecastPoint {
  t: number;
  yhat: number;
  lower: number;
  upper: number;
}

export interface ForecastTailPoint {
  t: number;
  forecast: number;
}

export interface BuildingConsumption extends Building {
  kwh: number;
}

export interface HealthBuilding extends Building {
  status: BuildingStatus;
  consumption: number;
  note: string;
  load: number;
}

export interface Alert {
  id: string;
  ts: number;
  building: Building;
  meter: string;
  type: string;
  sev: Severity;
  status: AlertStatus;
  actual: number | null;
  expected: number | null;
  dev: number | null;
}

export interface Kpi {
  key: string;
  label: string;
  value: string;
  unit: string;
  icon: IconName;
  tone: Tone;
  delta: number;
  deltaLabel: string;
  spark?: number[];
  isCount?: boolean;
}

export interface AnomalySummary {
  key: string;
  label: string;
  value: number;
  icon: IconName;
  tone: Tone;
  delta: number;
  sub: string;
}

export interface AnomalyEvent {
  id: string;
  site_id: string;
  building_id: string;
  primary_space_usage?: string | null;
  timestamp: string;
  start_time: string;
  end_time?: string | null;
  duration_hours?: number | null;
  severity: AnomalySeverity;
  type: string;
  actual_value?: number | null;
  expected_value?: number | null;
  deviation_percent?: number | null;
  reason: string;
}

export interface AnomalyOverview {
  total_anomalies: number;
  critical_anomalies: number;
  buildings_affected: number;
  most_affected_site?: string | null;
  time_min?: string | null;
  time_max?: string | null;
  severity_counts: Record<AnomalySeverity, number>;
  type_counts: Record<string, number>;
}

export interface AnomalyEventsResponse {
  total: number;
  limit: number;
  offset: number;
  items: AnomalyEvent[];
}

export interface AnomalyFacets {
  sites: string[];
  buildings: string[];
  severities: AnomalySeverity[];
  types: string[];
  primary_usage_types: string[];
}

export interface AnomalyTimelinePoint {
  timestamp: string;
  actual_value?: number | null;
  expected_value?: number | null;
}

export interface AnomalyTimelineGap {
  start_time: string;
  end_time: string;
  reason: string;
}

export interface AnomalyTimelineResponse {
  items: AnomalyEvent[];
  points: AnomalyTimelinePoint[];
  gaps: AnomalyTimelineGap[];
}

export interface ForecastKpi {
  key: string;
  label: string;
  value: string;
  unit: string;
  icon: IconName;
  tone: Tone;
  delta?: number;
  sub: string;
  text?: string;
  invertGood?: boolean;
}

export interface ModelPerf {
  key: "mae" | "rmse" | "mape";
  label: string;
  value: string;
  unit: string;
  desc: string;
  delta: number;
  tone: Tone;
}

export interface CauseAction {
  t: string;
  d: string;
  ic: IconName;
  tone?: Tone;
}
