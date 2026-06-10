import { AnomalySeverityBadge } from "@/components/common/primitives";
import { clock, displayLocationName } from "@/lib/format";
import type { AlertStatus, AnomalyEvent } from "@/types";

const ALERT_SEVERITIES = new Set<string>(["Critical", "High"]);
const STATUS_ORDER: Record<AlertStatus, number> = { Open: 0, Acknowledged: 1, Resolved: 2 };
const SEVERITY_ORDER: Record<string, number> = { Critical: 0, High: 1 };

function buildingLabel(buildingId: string) {
  return displayLocationName(null, buildingId);
}

export function AlertFeed({
  events,
  statuses,
  onAcknowledge,
  onResolve,
  onReopen,
  onSelect,
}: {
  events: AnomalyEvent[];
  statuses: Record<string, AlertStatus>;
  onAcknowledge: (id: string) => void;
  onResolve: (id: string) => void;
  onReopen: (id: string) => void;
  onSelect: (event: AnomalyEvent) => void;
}) {
  const alerts = events
    .filter((e) => ALERT_SEVERITIES.has(e.severity))
    .sort((a, b) => {
      const statusA = statuses[a.id] ?? "Open";
      const statusB = statuses[b.id] ?? "Open";
      const statusDiff = STATUS_ORDER[statusA] - STATUS_ORDER[statusB];
      if (statusDiff !== 0) return statusDiff;
      const sevDiff = (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9);
      if (sevDiff !== 0) return sevDiff;
      return new Date(b.start_time).getTime() - new Date(a.start_time).getTime();
    });

  if (alerts.length === 0) {
    return <div className="empty" style={{ padding: "18px 0" }}>No Critical or High alerts in view.</div>;
  }

  return (
    <div className="alert-feed">
      {alerts.map((event) => {
        const status = statuses[event.id] ?? "Open";
        return (
          <div
            className={`alert-item alert-item--${status.toLowerCase()}`}
            key={event.id}
            style={status === "Open" ? { borderLeftColor: `var(--anom-${event.severity.toLowerCase()})` } : undefined}
            onClick={() => onSelect(event)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onSelect(event); }}
          >
            <div className="alert-item-head">
              <AnomalySeverityBadge severity={event.severity} />
              <span className="alert-item-type">{event.type}</span>
              <span className="alert-item-time mono">{clock(new Date(event.start_time).getTime())}</span>
            </div>
            <div className="alert-item-building">{buildingLabel(event.building_id)}</div>
            <div className="alert-item-actions">
              {status === "Open" && (
                <button className="btn btn-sm" type="button" onClick={(e) => { e.stopPropagation(); onAcknowledge(event.id); }}>Acknowledge</button>
              )}
              {status !== "Resolved" && (
                <button className="btn btn-sm btn-ghost" type="button" onClick={(e) => { e.stopPropagation(); onResolve(event.id); }}>Resolve</button>
              )}
              {status === "Resolved" && (
                <button className="btn btn-sm btn-ghost" type="button" onClick={(e) => { e.stopPropagation(); onReopen(event.id); }}>Reopen</button>
              )}
              {status === "Acknowledged" && (
                <span className="alert-status-chip">Acknowledged</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
