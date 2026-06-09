"use client";

import { useEffect } from "react";
import { Icon } from "@/components/common/icons";
import { AnomalySeverityBadge, toneStyle } from "@/components/common/primitives";
import { clock, fmt, fmt1 } from "@/lib/format";
import type { AnomalyEvent } from "@/types";

function asTime(value: string) {
  return clock(new Date(value).getTime());
}

function valueLabel(value?: number | null) {
  return value == null ? "-" : `${fmt(value)} kWh`;
}

const HOUR_MS = 3_600_000;

function buildingLabel(buildingId: string) {
  const parts = buildingId.split("_");
  return parts.length >= 3 ? parts.slice(2).join("_") : buildingId;
}

function durationLabel(hours: number) {
  if (hours < 1) return "<1h";
  if (hours < 24) return `${Math.round(hours)}h`;
  const days = Math.floor(hours / 24);
  const rem = Math.round(hours % 24);
  return rem > 0 ? `${days}d ${rem}h` : `${days}d`;
}

export function AnomalyEventDrawer({ event, simNow, onClose }: { event: AnomalyEvent; simNow: number | null; onClose: () => void }) {
  useEffect(() => {
    const handler = (keyboardEvent: KeyboardEvent) => {
      if (keyboardEvent.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const endMs = event.end_time ? new Date(event.end_time).getTime() : null;
  const startMs = new Date(event.start_time).getTime();
  const isOngoing = simNow != null && endMs != null && endMs > simNow;
  const displayDuration = isOngoing && simNow != null
    ? (simNow - startMs) / HOUR_MS
    : (event.duration_hours ?? null);

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
            <dt>Building</dt><dd>{buildingLabel(event.building_id)}</dd>
            <dt>Usage</dt><dd>{event.primary_space_usage || "-"}</dd>
            <dt>Start</dt><dd className="mono">{asTime(event.start_time)}</dd>
            <dt>End</dt><dd className="mono">{isOngoing ? <span className="muted">Ongoing</span> : event.end_time ? asTime(event.end_time) : "-"}</dd>
            <dt>Duration</dt><dd className="mono">{displayDuration != null ? `${durationLabel(displayDuration)}${isOngoing ? " so far" : ""}` : "-"}</dd>
            <dt>Severity</dt><dd>{event.severity}</dd>
            <dt>Actual</dt><dd className="mono">{valueLabel(event.actual_value)}</dd>
            <dt>Expected</dt><dd className="mono">{valueLabel(event.expected_value)}</dd>
            <dt>Deviation</dt><dd className="mono">{deviation ?? "-"}</dd>
          </dl>


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
