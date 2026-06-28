"use client";

import { useCallback } from "react";
import { EChart } from "@/components/common/charts";
import type { ExperimentVersionDetail } from "@/lib/experiments-api";

// ---------------------------------------------------------------------------
// Local types — mirrors the private types in charts.tsx
// ---------------------------------------------------------------------------

interface ChartTheme {
  ink: string;
  muted: string;
  grid: string;
  surface: string;
}

// formatter params come from ECharts at runtime — typed as unknown and
// narrowed inside the formatter to avoid fighting ECharts' internal types
type TooltipParam = { seriesName?: string; name?: string; value?: unknown; color?: string };
type LabelParam = { value?: unknown };

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Metrics where lower = better (used for tooltip annotation). */
const LOWER_IS_BETTER = new Set([
  "mae", "rmse", "mape", "mean_error", "p10_error", "p90_error",
  "baseline_mae", "baseline_rmse",
]);

/** Human-readable metric labels. */
const METRIC_LABELS: Record<string, string> = {
  mae: "MAE",
  rmse: "RMSE",
  mape: "MAPE (%)",
  r2_score: "R²",
  mean_error: "Mean Error",
  p10_error: "P10 Error",
  p90_error: "P90 Error",
  performance_ratio: "Perf. Ratio",
};

/** Palette for up to 10 version series. */
const VERSION_COLORS = [
  "#2563eb", "#7c3aed", "#059669", "#d97706",
  "#dc2626", "#0891b2", "#9333ea", "#16a34a",
  "#ea580c", "#64748b",
];

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

function resolveDisplayMetrics(
  versionDetails: ExperimentVersionDetail[],
  commonMetrics: string[],
): string[] {
  if (commonMetrics.length > 0) return commonMetrics;
  const keys = new Set(
    versionDetails.flatMap((v) =>
      Object.keys(v.evaluation_metrics).filter((k) => v.evaluation_metrics[k] != null),
    ),
  );
  return [...keys].sort();
}

function formatMetricValue(raw: unknown): string {
  if (typeof raw === "number") return raw.toFixed(4);
  return "—";
}

function formatLabelValue(raw: unknown): string {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw.toFixed(2);
  return "";
}

function buildTooltipHtml(
  theme: ChartTheme,
  params: unknown[],
): string {
  const rows = params as TooltipParam[];
  const metricName = rows[0]?.name ?? "";
  const label = METRIC_LABELS[metricName] ?? metricName;
  const isLower = LOWER_IS_BETTER.has(metricName);
  let html = `<div style="font-weight:600;margin-bottom:6px">${label} <span style="font-size:10px;color:${theme.muted}">${isLower ? "lower is better" : "higher is better"}</span></div>`;
  rows.forEach((p) => {
    html += `<div style="display:flex;align-items:center;gap:8px;margin:2px 0">
      <span style="width:8px;height:8px;border-radius:2px;background:${p.color ?? "transparent"};display:inline-block"></span>
      <span style="flex:1">${p.seriesName ?? ""}</span>
      <b style="font-family:ui-monospace,monospace">${formatMetricValue(p.value)}</b>
    </div>`;
  });
  return html;
}

// ---------------------------------------------------------------------------
// Chart builder — returns Record<string, unknown> to stay compatible with
// the ChartBuilder type expected by the EChart wrapper in charts.tsx
// ---------------------------------------------------------------------------

function buildGroupedBarOption(
  versionDetails: ExperimentVersionDetail[],
  metrics: string[],
) {
  return (theme: ChartTheme): Record<string, unknown> => ({
    grid: { left: 8, right: 16, top: 36, bottom: 60, containLabel: true },
    legend: {
      top: 4,
      textStyle: { color: theme.ink, fontSize: 12 },
      itemWidth: 12,
      itemHeight: 12,
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: theme.surface,
      borderColor: theme.grid,
      borderWidth: 1,
      padding: [9, 12],
      textStyle: { color: theme.ink, fontSize: 12 },
      formatter: (params: unknown) =>
        buildTooltipHtml(theme, Array.isArray(params) ? params : []),
    },
    xAxis: {
      type: "category",
      data: metrics.map((m) => METRIC_LABELS[m] ?? m),
      axisLabel: { color: theme.muted, fontSize: 11.5, rotate: metrics.length > 5 ? 30 : 0 },
      axisLine: { lineStyle: { color: theme.grid } },
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      axisLabel: {
        color: theme.muted,
        fontSize: 11,
        fontFamily: "ui-monospace,monospace",
        formatter: (value: unknown) => {
          if (typeof value !== "number") return "";
          return Math.abs(value) >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);
        },
      },
      splitLine: { lineStyle: { color: theme.grid, type: "dashed" } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: versionDetails.map((detail, idx) => ({
      name: `v${detail.version}`,
      type: "bar",
      barGap: "10%",
      barMaxWidth: 40,
      data: metrics.map((m) => {
        const raw = detail.evaluation_metrics[m];
        return raw != null ? raw : null;
      }),
      itemStyle: {
        borderRadius: [3, 3, 0, 0],
        color: VERSION_COLORS[idx % VERSION_COLORS.length],
      },
      label: {
        show: versionDetails.length <= 4,
        position: "top",
        fontSize: 10,
        color: theme.muted,
        formatter: (p: LabelParam) => formatLabelValue(p.value),
      },
    })),
  });
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export function MetricsComparisonCharts({
  versionDetails,
  commonMetrics,
}: {
  versionDetails: ExperimentVersionDetail[];
  commonMetrics: string[];
}) {
  const metrics = resolveDisplayMetrics(versionDetails, commonMetrics);

  // useCallback memoises the builder — deps string avoids referential equality issues
  const build = useCallback(
    buildGroupedBarOption(versionDetails, metrics),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(versionDetails), metrics.join(",")],
  );

  if (metrics.length === 0) {
    return (
      <div style={{ padding: "16px 0", color: "var(--muted)", fontSize: 13 }}>
        No evaluation metrics available. Run <b>Evaluate</b> on the Monitoring page to generate them.
      </div>
    );
  }

  return (
    <EChart
      build={build}
      deps={[versionDetails, metrics]}
      height={300}
    />
  );
}
