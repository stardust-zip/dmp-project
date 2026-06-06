"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import * as echarts from "echarts";
import type { ECharts, EChartsOption } from "echarts";
import { ANOMALY_SERIES, BY_BUILDING, FC_HISTORY, FORECAST, PERF_TREND, TREND, TREND_FC } from "@/lib/mock-data";
import { clock, clockShort } from "@/lib/format";

interface ChartTheme {
  ink: string;
  muted: string;
  grid: string;
  surface: string;
  accent: string;
  red: string;
  orange: string;
  green: string;
  border2: string;
  dark: boolean;
}

type ChartOption = Record<string, unknown>;
type ChartBuilder = (theme: ChartTheme, instance: ECharts) => ChartOption;
type TooltipParam = { axisValue: string | number; name?: string; value: number | [number, number]; color?: string; seriesName?: string };

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function chartTheme(): ChartTheme {
  return {
    ink: cssVar("--ink") || "#0f172a",
    muted: cssVar("--muted") || "#64748b",
    grid: cssVar("--border") || "#e2e8f0",
    surface: cssVar("--surface") || "#fff",
    accent: cssVar("--accent-600") || "#2563eb",
    red: cssVar("--red") || "#dc2626",
    orange: cssVar("--orange") || "#ea580c",
    green: cssVar("--green") || "#16a34a",
    border2: cssVar("--border-2") || "#cbd5e1",
    dark: document.documentElement.getAttribute("data-theme") === "dark",
  };
}

function tooltipStyle(theme: ChartTheme) {
  return {
    backgroundColor: theme.surface,
    borderColor: theme.grid,
    borderWidth: 1,
    padding: [9, 12],
    textStyle: { color: theme.ink, fontSize: 12, fontFamily: getComputedStyle(document.body).fontFamily },
    extraCssText: `border-radius:9px;box-shadow:${theme.dark ? "0 8px 24px rgba(0,0,0,.5)" : "0 8px 24px rgba(15,23,42,.14)"};`,
  };
}

const MONO = '"SF Mono",ui-monospace,Menlo,Consolas,monospace';
const numFmt = (value: number) => Math.round(value).toLocaleString("en-US");
const pointValue = (value: number | [number, number]) => (Array.isArray(value) ? value[1] : value);

export function EChart({
  build,
  deps = [],
  height = 300,
  themeKey,
  style,
}: {
  build: ChartBuilder;
  deps?: unknown[];
  height?: number;
  themeKey?: string;
  style?: CSSProperties;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const instance = useRef<ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    instance.current = echarts.init(ref.current, null, { renderer: "canvas" });
    const ro = new ResizeObserver(() => instance.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      instance.current?.dispose();
      instance.current = null;
    };
  }, []);

  useEffect(() => {
    if (!instance.current) return;
    instance.current.setOption(build(chartTheme(), instance.current) as EChartsOption, true);
  }, [build, themeKey, ...deps]);

  return <div ref={ref} className="chart" style={{ height, width: "100%", ...style }} />;
}

export function buildTrend(range: string, areaStyle: boolean): ChartBuilder {
  return (theme) => {
    const hist = TREND[range] ?? TREND["24h"];
    const fc = TREND_FC[range] ?? TREND_FC["24h"];
    const actual = hist.map((point) => [point.t, point.actual]);
    const expected = hist.map((point) => [point.t, point.expected]);
    const fcLine = [[hist[hist.length - 1].t, hist[hist.length - 1].actual], ...fc.map((point) => [point.t, point.forecast])];
    const fmtX = range === "24h" ? (t: number) => clockShort(t) : (t: number) => new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" });

    return {
      grid: { left: 8, right: 14, top: 16, bottom: 26, containLabel: true },
      tooltip: {
        trigger: "axis",
        ...tooltipStyle(theme),
        axisPointer: { type: "line", lineStyle: { color: theme.border2, width: 1 } },
        formatter: (params: TooltipParam[]) => {
          const t = Number(params[0].axisValue);
          let html = `<div style="font-size:11px;color:${theme.muted};margin-bottom:5px">${clock(t)}</div>`;
          params.forEach((param) => {
            html += `<div style="display:flex;align-items:center;gap:8px;margin:2px 0"><span style="width:8px;height:8px;border-radius:2px;background:${param.color};display:inline-block"></span><span style="flex:1">${param.seriesName}</span><b style="font-family:${MONO}">${numFmt(pointValue(param.value))} kWh</b></div>`;
          });
          return html;
        },
      },
      xAxis: {
        type: "time",
        boundaryGap: false,
        axisLine: { lineStyle: { color: theme.grid } },
        axisTick: { show: false },
        axisLabel: { color: theme.muted, fontSize: 11, formatter: (value: number) => fmtX(value), hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: theme.muted, fontSize: 11, fontFamily: MONO, formatter: (value: number) => (value >= 1000 ? `${(value / 1000).toFixed(0)}k` : value) },
        splitLine: { lineStyle: { color: theme.grid, type: "dashed" } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          name: "Actual Consumption",
          type: "line",
          smooth: 0.3,
          showSymbol: false,
          data: actual,
          lineStyle: { width: 2.4, color: theme.accent },
          itemStyle: { color: theme.accent },
          areaStyle: areaStyle
            ? { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: theme.dark ? "rgba(37,99,235,.36)" : "rgba(37,99,235,.20)" }, { offset: 1, color: "rgba(37,99,235,0)" }]) }
            : undefined,
          z: 3,
        },
        { name: "Expected Baseline", type: "line", smooth: 0.3, showSymbol: false, data: expected, lineStyle: { width: 1.4, color: theme.muted, type: [5, 4] }, z: 2 },
        {
          name: "Forecast",
          type: "line",
          smooth: 0.3,
          showSymbol: false,
          data: fcLine,
          lineStyle: { width: 2.2, color: "#7c3aed", type: [6, 5] },
          itemStyle: { color: "#7c3aed" },
          areaStyle: areaStyle
            ? { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "rgba(124,58,237,.16)" }, { offset: 1, color: "rgba(124,58,237,0)" }]) }
            : undefined,
          z: 3,
        },
      ],
    };
  };
}

export function buildByBuilding(): ChartBuilder {
  return (theme) => {
    const data = [...BY_BUILDING].slice(0, 8).reverse();
    const max = Math.max(...data.map((entry) => entry.kwh));
    return {
      grid: { left: 6, right: 56, top: 6, bottom: 6, containLabel: true },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        ...tooltipStyle(theme),
        formatter: (params: TooltipParam[]) => {
          const param = params[0];
          return `<div style="font-weight:600;margin-bottom:3px">${param.name}</div><div style="display:flex;gap:10px;align-items:center"><span style="color:${theme.muted}">Consumption</span><b style="font-family:${MONO}">${numFmt(pointValue(param.value))} kWh</b></div>`;
        },
      },
      xAxis: { type: "value", show: false, max: max * 1.02 },
      yAxis: {
        type: "category",
        data: data.map((entry) => entry.name),
        axisLabel: { color: theme.ink, fontSize: 11.5, fontWeight: 500 },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          type: "bar",
          data: data.map((entry) => ({ value: entry.kwh })),
          barWidth: 13,
          label: { show: true, position: "right", formatter: (param: { value: number }) => numFmt(param.value), color: theme.muted, fontSize: 11, fontFamily: MONO, fontWeight: 600 },
          itemStyle: {
            borderRadius: [0, 4, 4, 0],
            color: (param: { value: number }) => {
              const ratio = param.value / max;
              return new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                { offset: 0, color: theme.dark ? "#1e3a8a" : "#93c5fd" },
                { offset: 1, color: ratio > 0.85 ? theme.accent : ratio > 0.6 ? "#3b82f6" : "#60a5fa" },
              ]);
            },
          },
        },
      ],
    };
  };
}

export function buildAnomalyTimeline(): ChartBuilder {
  return (theme) => {
    const actual = ANOMALY_SERIES.map((point) => [point.t, point.actual]);
    const baseline = ANOMALY_SERIES.map((point) => [point.t, point.expected]);
    const marks = ANOMALY_SERIES.filter((point) => point.anomaly).map((point) => ({
      value: [point.t, point.actual],
      itemStyle: { color: point.anomaly === "critical" ? theme.red : theme.orange, borderColor: theme.surface, borderWidth: 2 },
      symbolSize: 11,
    }));

    return {
      grid: { left: 8, right: 16, top: 18, bottom: 54, containLabel: true },
      tooltip: {
        trigger: "axis",
        ...tooltipStyle(theme),
        axisPointer: { type: "line", lineStyle: { color: theme.border2 } },
      },
      xAxis: { type: "time", boundaryGap: false, axisLine: { lineStyle: { color: theme.grid } }, axisTick: { show: false }, axisLabel: { color: theme.muted, fontSize: 11, hideOverlap: true }, splitLine: { show: false } },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: theme.muted, fontSize: 11, fontFamily: MONO, formatter: (value: number) => (value >= 1000 ? `${(value / 1000).toFixed(1)}k` : value) },
        splitLine: { lineStyle: { color: theme.grid, type: "dashed" } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      dataZoom: [
        { type: "inside", start: 40, end: 100 },
        { type: "slider", start: 40, end: 100, height: 18, bottom: 14, borderColor: theme.grid, fillerColor: theme.dark ? "rgba(37,99,235,.18)" : "rgba(37,99,235,.10)", textStyle: { color: theme.muted, fontSize: 10 } },
      ],
      series: [
        { name: "Expected Baseline", type: "line", smooth: 0.2, showSymbol: false, data: baseline, lineStyle: { width: 1.5, color: theme.muted, type: [5, 4] }, z: 2 },
        {
          name: "Actual Consumption",
          type: "line",
          smooth: 0.2,
          showSymbol: false,
          data: actual,
          lineStyle: { width: 2.2, color: theme.accent },
          itemStyle: { color: theme.accent },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: theme.dark ? "rgba(37,99,235,.28)" : "rgba(37,99,235,.14)" }, { offset: 1, color: "rgba(37,99,235,0)" }]) },
          markPoint: { data: marks, symbol: "circle", label: { show: false } },
          z: 3,
        },
      ],
    };
  };
}

export function buildForecastChart(horizon: "day" | "week" | "month"): ChartBuilder {
  return (theme) => {
    const forecast = FORECAST[horizon];
    const splitT = FC_HISTORY[FC_HISTORY.length - 1].t;
    const actual = FC_HISTORY.map((point) => [point.t, point.actual]);
    const yhat = [[splitT, FC_HISTORY[FC_HISTORY.length - 1].actual], ...forecast.map((point) => [point.t, point.yhat])];
    const lower = forecast.map((point) => [point.t, point.lower]);
    const upperDiff = forecast.map((point) => [point.t, point.upper - point.lower]);

    return {
      grid: { left: 8, right: 16, top: 18, bottom: 28, containLabel: true },
      tooltip: { trigger: "axis", ...tooltipStyle(theme), axisPointer: { type: "line", lineStyle: { color: theme.border2 } } },
      xAxis: {
        type: "time",
        boundaryGap: false,
        axisLine: { lineStyle: { color: theme.grid } },
        axisTick: { show: false },
        axisLabel: { color: theme.muted, fontSize: 11, hideOverlap: true, formatter: (value: number) => new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric" }) },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: theme.muted, fontSize: 11, fontFamily: MONO, formatter: (value: number) => `${(value / 1000).toFixed(0)}k` },
        splitLine: { lineStyle: { color: theme.grid, type: "dashed" } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        { name: "ci-lower", type: "line", data: lower, stack: "ci", showSymbol: false, lineStyle: { opacity: 0 }, z: 1, silent: true, tooltip: { show: false } },
        { name: "ci-upper", type: "line", data: upperDiff, stack: "ci", showSymbol: false, lineStyle: { opacity: 0 }, areaStyle: { color: "rgba(124,58,237,.16)" }, z: 1, silent: true, tooltip: { show: false } },
        {
          name: "Historical Consumption",
          type: "line",
          smooth: 0.25,
          showSymbol: false,
          data: actual,
          lineStyle: { width: 2.2, color: theme.accent },
          itemStyle: { color: theme.accent },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: theme.dark ? "rgba(37,99,235,.22)" : "rgba(37,99,235,.12)" }, { offset: 1, color: "rgba(37,99,235,0)" }]) },
          markArea: { silent: true, itemStyle: { color: theme.dark ? "rgba(124,58,237,.07)" : "rgba(124,58,237,.05)" }, data: [[{ xAxis: splitT }, { xAxis: forecast[forecast.length - 1].t }]] },
          z: 3,
        },
        {
          name: "Forecast Consumption",
          type: "line",
          smooth: 0.25,
          showSymbol: false,
          data: yhat,
          lineStyle: { width: 2.2, color: "#7c3aed", type: [6, 5] },
          itemStyle: { color: "#7c3aed" },
          markLine: { silent: true, symbol: "none", lineStyle: { color: theme.border2, type: "solid", width: 1 }, label: { show: true, position: "insideStartTop", formatter: "Now", color: theme.muted, fontSize: 10 }, data: [{ xAxis: splitT }] },
          z: 4,
        },
      ],
    };
  };
}

export function buildMiniTrend(series: number[], color: string): ChartBuilder {
  return (theme) => ({
    grid: { left: 2, right: 2, top: 6, bottom: 4 },
    xAxis: { type: "category", show: false, boundaryGap: false, data: series.map((_, index) => index) },
    yAxis: { type: "value", show: false, scale: true },
    tooltip: { trigger: "axis", ...tooltipStyle(theme) },
    series: [
      {
        type: "line",
        data: series,
        smooth: 0.3,
        showSymbol: false,
        lineStyle: { width: 2, color },
        itemStyle: { color },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color }, { offset: 1, color: "transparent" }]), opacity: 0.12 },
      },
    ],
  });
}
