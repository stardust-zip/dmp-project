"use client";

import { useEffect } from "react";
import { Icon } from "@/components/common/icons";
import { SeverityBadge, StatusBadge, toneStyle } from "@/components/common/primitives";
import { ACTION_LIB, causesFor } from "@/lib/mock-data";
import { clock, fmt } from "@/lib/format";
import type { Alert } from "@/types";

export function AlertDrawer({ alert, onClose }: { alert: Alert; onClose: () => void }) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const causes = causesFor(alert.type);
  const devColor = alert.dev == null ? "var(--muted)" : alert.dev > 0 ? "var(--red)" : "var(--green)";

  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Alert Investigation">
        <div className="drawer-head">
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <span className="card-icon" style={toneStyle(alert.sev === "critical" ? "red" : alert.sev === "warning" ? "orange" : "accent")}>
                <Icon name="alert" />
              </span>
              <SeverityBadge sev={alert.sev} />
              <StatusBadge status={alert.status} />
            </div>
            <h3 style={{ margin: "2px 0 1px", fontSize: 16, fontWeight: 680, letterSpacing: "-.01em" }}>Alert Investigation</h3>
            <div className="mono" style={{ fontSize: 11.5, color: "var(--muted)" }}>{alert.id} - {alert.type}</div>
          </div>
          <button className="icon-btn" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>

        <div className="drawer-body">
          <div className="sec-label">
            <Icon name="info" style={{ width: 13, height: 13 }} /> Details
          </div>
          <dl className="dl">
            <dt>Alert ID</dt><dd className="mono">{alert.id}</dd>
            <dt>Building</dt><dd>{alert.building.name}</dd>
            <dt>Site</dt><dd>{alert.building.site}</dd>
            <dt>Meter</dt><dd className="mono">{alert.meter}</dd>
            <dt>Timestamp</dt><dd className="mono">{clock(alert.ts)}</dd>
            <dt>Actual Consumption</dt><dd className="mono">{alert.actual != null ? `${fmt(alert.actual)} kWh` : "No data"}</dd>
            <dt>Expected Consumption</dt><dd className="mono">{alert.expected != null ? `${fmt(alert.expected)} kWh` : "-"}</dd>
            <dt>Deviation</dt><dd className="mono" style={{ color: devColor, fontWeight: 700 }}>{alert.dev == null ? "-" : `${alert.dev > 0 ? "+" : ""}${alert.dev.toFixed(1)}%`}</dd>
            <dt>Severity</dt><dd style={{ textTransform: "capitalize" }}>{alert.sev}</dd>
          </dl>

          {alert.dev != null && (
            <div style={{ marginTop: 12, padding: "11px 13px", border: "1px solid var(--border)", borderRadius: 9, background: "var(--surface-2)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>
                <span>Expected baseline</span>
                <span>Actual reading</span>
              </div>
              <div className="bar" style={{ height: 7 }}>
                <i style={{ width: `${Math.min(100, Math.abs(alert.dev) + 50)}%`, background: devColor }} />
              </div>
            </div>
          )}

          <div className="sec-label">
            <Icon name="help" style={{ width: 13, height: 13 }} /> Possible Causes
          </div>
          {causes.map((cause, index) => (
            <div className="cause" key={`${cause.t}-${index}`}>
              <span className="cause-ic" style={toneStyle(cause.tone ?? "accent")}>
                <Icon name={cause.ic} />
              </span>
              <div>
                <b>{cause.t}</b>
                <span>{cause.d}</span>
              </div>
            </div>
          ))}

          <div className="sec-label">
            <Icon name="wrench" style={{ width: 13, height: 13 }} /> Recommended Actions
          </div>
          {ACTION_LIB.map((action, index) => (
            <div className="cause" key={`${action.t}-${index}`}>
              <span className="cause-ic" style={toneStyle("accent")}>
                <Icon name={action.ic} />
              </span>
              <div>
                <b>{action.t}</b>
                <span>{action.d}</span>
              </div>
            </div>
          ))}
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
