"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Icon } from "@/components/common/icons";
import { fmt } from "@/lib/format";
import type { AnomalySeverity, IconName, Kpi, Severity, Tone } from "@/types";

const TONES: Record<Tone, [string, string]> = {
  accent: ["var(--accent-soft)", "var(--accent-600)"],
  slate: ["var(--surface-3)", "var(--muted)"],
  red: ["var(--red-soft)", "var(--red)"],
  orange: ["var(--orange-soft)", "var(--orange)"],
  green: ["var(--green-soft)", "var(--green)"],
  violet: ["color-mix(in oklab, #7c3aed 12%, var(--surface))", "#7c3aed"],
  amber: ["var(--amber-soft)", "var(--amber)"],
};

export function toneStyle(tone: Tone): CSSProperties {
  const [background, color] = TONES[tone] ?? TONES.slate;
  return { background, color };
}

export function SeverityBadge({ sev }: { sev: Severity }) {
  const labels: Record<Severity, string> = { critical: "Critical", warning: "Warning", info: "Info" };
  return (
    <span className={`badge badge-${sev}`}>
      <i className="bdot" />
      {labels[sev]}
    </span>
  );
}

export function AnomalySeverityBadge({ severity }: { severity: AnomalySeverity }) {
  const key = severity.toLowerCase();
  return (
    <span className={`badge badge-anomaly-${key}`}>
      <i className="bdot" />
      {severity}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const key = status.toLowerCase();
  const cls = key === "resolved" ? "badge-resolved" : key === "acknowledged" ? "badge-ack" : "badge-open";
  return (
    <span className={`badge ${cls}`}>
      <i className="bdot" />
      {status}
    </span>
  );
}

export function Sparkline({
  data,
  color = "var(--accent-600)",
  fill = true,
  h = 26,
  w = 120,
}: {
  data: number[];
  color?: string;
  fill?: boolean;
  h?: number;
  w?: number;
}) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const points = data.map((value, index) => [(index / (data.length - 1)) * w, h - ((value - min) / range) * (h - 4) - 2]);
  const d = points.map((point, index) => `${index ? "L" : "M"}${point[0].toFixed(1)} ${point[1].toFixed(1)}`).join(" ");
  const area = `${d} L${w} ${h} L0 ${h} Z`;
  const gid = `sg${Math.round(min * 1000)}${data.length}${Math.round(max)}`;

  return (
    <svg className="kpi-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ height: h }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.20" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {fill && <path d={area} fill={`url(#${gid})`} />}
      <path d={d} fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function KpiCard({ kpi }: { kpi: Kpi }) {
  const upBad = kpi.key === "anom" || kpi.key === "crit";
  const positive = kpi.delta > 0;
  const deltaCls = upBad ? (positive ? "up" : "down") : positive ? "down" : "up";
  const neutral = kpi.key === "today" || kpi.key === "yest" || kpi.key === "forecast";

  return (
    <div className="kpi">
      <div className="kpi-top">
        <span className="kpi-label">{kpi.label}</span>
        <span className="kpi-ic" style={toneStyle(kpi.tone)}>
          <Icon name={kpi.icon} />
        </span>
      </div>
      <div className="row" style={{ alignItems: "baseline", gap: 0 }}>
        <span className="kpi-val">{kpi.value}</span>
        {kpi.unit && <span className="kpi-unit">{kpi.unit}</span>}
      </div>
      {kpi.value !== "-" && (
        <div className="kpi-foot">
          <span className={`delta ${neutral ? (positive ? "up" : "down") : deltaCls}`}>
            <Icon name={positive ? "arrowUp" : "arrowDown"} style={{ width: 12, height: 12 }} />
            {positive ? "+" : ""}
            {kpi.delta}
            {kpi.isCount ? "" : kpi.key === "quality" ? " pts" : "%"}
          </span>
          <span style={{ color: "var(--muted-2)" }}>.</span>
          <span>{kpi.deltaLabel}</span>
        </div>
      )}
    </div>
  );
}

export function Card({
  title,
  sub,
  icon,
  iconTone = "accent",
  actions,
  children,
  bodyClass = "",
  noBody = false,
  style,
}: {
  title?: string;
  sub?: string;
  icon?: IconName;
  iconTone?: Tone;
  actions?: ReactNode;
  children?: ReactNode;
  bodyClass?: string;
  noBody?: boolean;
  style?: CSSProperties;
}) {
  return (
    <section className="card" style={style}>
      {(title || actions) && (
        <div className="card-head">
          <div className="card-title-wrap">
            {icon && (
              <span className="card-icon" style={toneStyle(iconTone)}>
                <Icon name={icon} />
              </span>
            )}
            <div>
              <h3>{title}</h3>
              {sub && <div className="sub">{sub}</div>}
            </div>
          </div>
          {actions}
        </div>
      )}
      {noBody ? children : <div className={`card-body ${bodyClass}`}>{children}</div>}
    </section>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (value: T) => void;
}) {
  return (
    <div className="seg">
      {options.map((option) => (
        <button key={option.value} className={value === option.value ? "on" : ""} onClick={() => onChange(option.value)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
    </div>
  );
}

export function FormMessage({
  children,
  tone = "info",
}: {
  children: ReactNode;
  tone?: "info" | "error" | "success";
}) {
  return (
    <div className={`form-message form-message-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <Icon name={tone === "success" ? "check" : tone === "error" ? "alert" : "info"} />
      <span>{children}</span>
    </div>
  );
}

export function Modal({
  title,
  description,
  labelledBy,
  children,
  footer,
  className = "",
  onClose,
}: {
  title: string;
  description?: ReactNode;
  labelledBy?: string;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  onClose: () => void;
}) {
  const titleId = labelledBy ?? `${title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}-title`;

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className={`app-modal ${className}`} role="dialog" aria-modal="true" aria-labelledby={titleId} onMouseDown={(event) => event.stopPropagation()}>
        <div className="app-modal-head">
          <div>
            <h2 id={titleId}>{title}</h2>
            {description && <span>{description}</span>}
          </div>
          <button className="icon-btn" type="button" aria-label={`Close ${title} dialog`} onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        <div className="app-modal-body">{children}</div>
        {footer && <div className="app-modal-foot">{footer}</div>}
      </section>
    </div>
  );
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  disabled,
  openSignal,
  searchable = false,
  searchPlaceholder = "Search...",
}: {
  value: T;
  onChange: (value: T) => void;
  options: Array<{ value: T; label: string }>;
  disabled?: boolean;
  openSignal?: number;
  searchable?: boolean;
  searchPlaceholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const selected = options.find((option) => option.value === value) ?? options[0];
  const visibleOptions = searchable && search.trim()
    ? options.filter((option) => `${option.label} ${option.value}`.toLowerCase().includes(search.trim().toLowerCase()))
    : options;

  useEffect(() => {
    if (!open) return;

    const closeIfOutside = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    document.addEventListener("pointerdown", closeIfOutside);
    document.addEventListener("keydown", closeOnEscape);

    return () => {
      document.removeEventListener("pointerdown", closeIfOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  useEffect(() => {
    if (openSignal == null || disabled || options.length === 0) return;
    const timeout = window.setTimeout(() => setOpen(true), 0);
    return () => window.clearTimeout(timeout);
  }, [disabled, openSignal, options.length]);

  const choose = (nextValue: T) => {
    onChange(nextValue);
    setOpen(false);
    setSearch("");
  };

  return (
    <div className="select-wrap" ref={wrapRef}>
      <button
        className={`select-trigger ${open ? "is-open" : ""}`}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => !disabled && setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        <span>{selected?.label ?? "Select"}</span>
        <Icon name="chevDown" />
      </button>
      {open && (
        <div className="select-menu" role="listbox" tabIndex={-1}>
          {searchable && (
            <div className="select-search">
              <Icon name="search" />
              <input
                autoFocus
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                onKeyDown={(event) => event.stopPropagation()}
                placeholder={searchPlaceholder}
              />
            </div>
          )}
          {visibleOptions.length === 0 && <div className="select-empty">No matches</div>}
          {visibleOptions.map((option) => (
            <button
              className={`select-option ${option.value === value ? "is-selected" : ""}`}
              key={option.value}
              type="button"
              role="option"
              aria-selected={option.value === value}
              onClick={() => choose(option.value)}
            >
              <span title={option.value}>{option.label}</span>
              {option.value === value && <Icon name="check" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Spinner({ size = 15 }: { size?: number }) {
  return <Icon name="refresh" className="spin" style={{ width: size, height: size }} />;
}

export function ConsumptionValue({ value }: { value: number }) {
  return <>{fmt(value)}</>;
}
