"use client";

import { useEffect } from "react";
import { Icon } from "@/components/common/icons";
import { AnomalySeverityBadge, toneStyle } from "@/components/common/primitives";
import { clock, fmt, fmt1 } from "@/lib/format";
import type { AnomalyEvent, Tone } from "@/types";

function asTime(value: string) {
  return clock(new Date(value).getTime());
}

function durationLabel(hours?: number | null) {
  if (hours == null) return "-";
  if (hours < 24) return `${fmt1(hours)}h`;
  const days = Math.floor(hours / 24);
  const rest = Math.round(hours % 24);
  return rest ? `${days}d ${rest}h` : `${days}d`;
}

function valueLabel(value?: number | null) {
  return value == null ? "-" : `${fmt(value)} kWh`;
}

function actionFor(event: AnomalyEvent) {
  const type = event.type.toLowerCase();
  if (type.includes("missing") || type.includes("usable")) {
    return {
      title: "Check meter connectivity",
      desc: "Verify gateway status, meter power, and telemetry ingestion for this building.",
      icon: "wifi" as const,
      tone: "orange" as Tone,
    };
  }
  if (type.includes("flatline") || type.includes("near-zero")) {
    return {
      title: "Inspect meter readings",
      desc: "Confirm the meter is updating and the connected load is not stuck at a constant value.",
      icon: "gauge" as const,
      tone: "slate" as Tone,
    };
  }
  if (type.includes("spike") || type.includes("high")) {
    return {
      title: "Inspect high-load equipment",
      desc: "Check HVAC, process equipment, and schedule overrides around the anomaly time.",
      icon: "wrench" as const,
      tone: "red" as Tone,
    };
  }
  return {
    title: "Review operating schedule",
    desc: "Compare the event against occupancy, shutdown windows, and planned low-load periods.",
    icon: "clock" as const,
    tone: "accent" as Tone,
  };
}

export function AnomalyEventDrawer({ event, onClose }: { event: AnomalyEvent; onClose: () => void }) {
  useEffect(() => {
    const handler = (keyboardEvent: KeyboardEvent) => {
      if (keyboardEvent.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const action = actionFor(event);
  const deviation = event.deviation_percent == null ? null : `${event.deviation_percent > 0 ? "+" : ""}${fmt1(event.deviation_percent)}%`;

  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Anomaly details">
        <div className="drawer-head">
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <span className="card-icon" style={toneStyle(event.severity === "Critical" ? "red" : event.severity === "High" ? "orange" : event.severity === "Medium" ? "amber" : "accent")}>
                <Icon name="alert" />
              </span>
              <AnomalySeverityBadge severity={event.severity} />
            </div>
            <h3 style={{ margin: "2px 0 1px", fontSize: 16, fontWeight: 680 }}>{event.type}</h3>
            <div className="mono" style={{ fontSize: 11.5, color: "var(--muted)" }}>{event.id}</div>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close anomaly details">
            <Icon name="x" />
          </button>
        </div>

        <div className="drawer-body">
          <div className="sec-label">
            <Icon name="info" style={{ width: 13, height: 13 }} /> Event
          </div>
          <dl className="dl">
            <dt>Site</dt><dd>{event.site_id}</dd>
            <dt>Building</dt><dd>{event.building_id}</dd>
            <dt>Usage</dt><dd>{event.primary_space_usage || "-"}</dd>
            <dt>Start</dt><dd className="mono">{asTime(event.start_time)}</dd>
            <dt>End</dt><dd className="mono">{event.end_time ? asTime(event.end_time) : "-"}</dd>
            <dt>Duration</dt><dd className="mono">{durationLabel(event.duration_hours)}</dd>
            <dt>Severity</dt><dd>{event.severity}</dd>
            <dt>Actual</dt><dd className="mono">{valueLabel(event.actual_value)}</dd>
            <dt>Expected</dt><dd className="mono">{valueLabel(event.expected_value)}</dd>
            <dt>Deviation</dt><dd className="mono">{deviation ?? "-"}</dd>
          </dl>

          <div className="sec-label">
            <Icon name="help" style={{ width: 13, height: 13 }} /> Explanation
          </div>
          <div className="cause">
            <span className="cause-ic" style={toneStyle("accent")}>
              <Icon name="pulse" />
            </span>
            <div>
              <b>{event.type}</b>
              <span>{event.reason}</span>
            </div>
          </div>

          <div className="sec-label">
            <Icon name="wrench" style={{ width: 13, height: 13 }} /> Suggested Action
          </div>
          <div className="cause">
            <span className="cause-ic" style={toneStyle(action.tone)}>
              <Icon name={action.icon} />
            </span>
            <div>
              <b>{action.title}</b>
              <span>{action.desc}</span>
            </div>
          </div>
        </div>

        <div className="drawer-foot">
          <button className="btn btn-primary" style={{ flex: 1 }}>
            <Icon name="check" /> Acknowledge
          </button>
          <button className="btn" style={{ flex: 1 }}>
            <Icon name="users" /> Assign
          </button>
          <button className="btn btn-ghost" onClick={onClose}>Dismiss</button>
        </div>
      </aside>
    </>
  );
}
