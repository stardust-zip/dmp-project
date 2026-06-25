"use client";

import { useMemo } from "react";
import type { PerformanceTimelineResponse } from "@/lib/monitoring-api";
import { EChart } from "@/components/common/charts";
import { Card } from "@/components/common/primitives";

export function PerformanceTab({ data }: { data: PerformanceTimelineResponse | null }) {
  if (!data || data.metrics.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: 40, color: "var(--muted)" }}>
        No performance data available. Trigger an evaluation to compute metrics.
      </div>
    );
  }

  const chartOption = useMemo(() => {
    const categories = data.metrics.map((m) => new Date(m.computed_at).toLocaleString());
    const maeData = data.metrics.map((m) => m.mae ?? null);
    const rmseData = data.metrics.map((m) => m.rmse ?? null);
    const baselineMae = data.metrics[0]?.baseline_mae;
    const baselineRmse = data.metrics[0]?.baseline_rmse;

    const series: Array<Record<string, unknown>> = [
      { name: "MAE", type: "line", data: maeData, smooth: true },
      { name: "RMSE", type: "line", data: rmseData, smooth: true },
    ];

    if (baselineMae) {
      series.push({
        name: "Baseline MAE",
        type: "line",
        data: Array(categories.length).fill(baselineMae),
        lineStyle: { type: "dashed", width: 1.5 },
        symbol: "none",
      });
    }
    if (baselineRmse) {
      series.push({
        name: "Baseline RMSE",
        type: "line",
        data: Array(categories.length).fill(baselineRmse),
        lineStyle: { type: "dashed", width: 1.5 },
        symbol: "none",
      });
    }

    return {
      tooltip: { trigger: "axis" as const },
      legend: { data: series.map((s) => s.name as string), top: 0 },
      grid: { left: 50, right: 20, top: 40, bottom: 30 },
      xAxis: { type: "category" as const, data: categories, axisLabel: { fontSize: 11 } },
      yAxis: { type: "value" as const, splitLine: { lineStyle: { type: "dashed" } } },
      series,
    };
  }, [data]);

  const ratioChartOption = useMemo(() => {
    const categories = data.metrics.map((m) => new Date(m.computed_at).toLocaleString());
    const ratioData = data.metrics.map((m) => m.performance_ratio ?? null);

    return {
      tooltip: { trigger: "axis" as const },
      legend: { data: ["Performance Ratio"], top: 0 },
      grid: { left: 50, right: 20, top: 40, bottom: 30 },
      xAxis: { type: "category" as const, data: categories, axisLabel: { fontSize: 11 } },
      yAxis: { type: "value" as const, min: 0.5, max: 2, splitLine: { lineStyle: { type: "dashed" } } },
      series: [
        {
          name: "Performance Ratio",
          type: "line" as const,
          data: ratioData,
          smooth: true,
          markLine: {
            silent: true,
            lineStyle: { width: 1.5 },
            data: [
              { yAxis: 1.0, name: "Baseline" },
              { yAxis: 1.2, name: "Warning" },
              { yAxis: 1.5, name: "Critical" },
            ],
          },
        },
      ],
    };
  }, [data]);

  const first = data.metrics[0];
  const rangeSub = first
    ? `${new Date(first.period_start).toLocaleDateString()} \u2013 ${new Date(first.period_end).toLocaleDateString()}`
    : "";

  return (
    <div className="grid" style={{ gap: "var(--gap)" }}>
      <Card
        title="Performance Metrics Over Time"
        icon="pulse"
        sub={`${data.model_name} v${data.model_version} \u00B7 ${rangeSub}`}
      >
        <EChart build={() => chartOption} height={280} />
      </Card>
      <Card title="Performance Ratio" icon="trend" sub="Current MAE / Baseline MAE \u2014 1.0 = baseline, >1.2 = warning, >1.5 = critical">
        <EChart build={() => ratioChartOption} height={240} />
      </Card>
    </div>
  );
}
