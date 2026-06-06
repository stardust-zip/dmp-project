export type Severity = "critical" | "warning" | "info";
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
