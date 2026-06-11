export function fmt(n: number) {
  return Math.round(n).toLocaleString("en-US");
}

export function fmtKwh(n: number) {
  if (Math.abs(n) < 1) {
    return n.toLocaleString("en-US", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  }
  return Math.round(n).toLocaleString("en-US");
}

export function fmt1(n: number) {
  return Number(n).toLocaleString("en-US", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

export function timeAgo(ts: number) {
  const seconds = Math.floor((Date.now() - ts) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function clock(ts: number) {
  return new Date(ts).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function clockShort(ts: number) {
  return new Date(ts).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

const HUMAN_TOKEN_OVERRIDES: Record<string, string> = {
  ai: "AI",
  api: "API",
  co2: "CO2",
  db: "DB",
  dmp: "DMP",
  hvac: "HVAC",
  id: "ID",
  kwh: "kWh",
};

const ENERGY_MODEL_PREFIX = "dmp_energy_prediction";
const DEVICE_PREFIXES = ["meter"];
const LOCATION_PREFIXES = ["building", "site"];

function titleToken(token: string) {
  const lower = token.toLowerCase();
  return HUMAN_TOKEN_OVERRIDES[lower] ?? `${lower.charAt(0).toUpperCase()}${lower.slice(1)}`;
}

export function humanizeIdentifier(value?: string | null) {
  if (!value?.trim()) return "Unspecified";
  return value
    .trim()
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map(titleToken)
    .join(" ");
}

function stripKnownPrefix(value: string, prefixes: string[]) {
  const normalized = value.trim();
  const lower = normalized.toLowerCase();
  const prefix = prefixes.find((candidate) => lower === candidate || lower.startsWith(`${candidate}_`) || lower.startsWith(`${candidate} `));
  if (!prefix) return normalized;
  return normalized.slice(prefix.length).replace(/^[_\s-]+/, "");
}

export function displayLocationName(name?: string | null, id?: string | null) {
  const source = name?.trim() || id?.trim();
  if (!source) return "Unnamed Location";
  return humanizeIdentifier(stripKnownPrefix(source, LOCATION_PREFIXES));
}

export function isSiteLocation(location: { location_type?: string | null; parent_id?: string | null }) {
  return location.location_type?.toLowerCase() === "site";
}

export function isBuildingLocation(location: { location_type?: string | null; parent_id?: string | null }) {
  return !isSiteLocation(location);
}

export function locationSearchText(location: { id: string; name?: string | null; location_type?: string | null; parent_id?: string | null }, parent?: { id: string; name?: string | null } | null) {
  return [
    location.id,
    location.name ?? "",
    displayLocationName(location.name, location.id),
    location.location_type ?? "",
    location.parent_id ?? "",
    parent?.id ?? "",
    parent?.name ?? "",
    parent ? displayLocationName(parent.name, parent.id) : "",
  ].join(" ").toLowerCase();
}

export function displayDeviceName(id?: string | null) {
  if (!id?.trim()) return "Unnamed Device";
  const parts = stripKnownPrefix(id, DEVICE_PREFIXES).split("_").filter(Boolean);
  if (parts.length < 2) return humanizeIdentifier(id);

  const [deviceType, ...locationParts] = parts;
  return `${humanizeIdentifier(deviceType)} Meter - ${humanizeIdentifier(locationParts.join("_"))}`;
}

export function displayModelName(name?: string | null) {
  if (!name?.trim()) return "Unnamed Model";
  const normalized = name.trim();
  if (!normalized.toLowerCase().startsWith(`${ENERGY_MODEL_PREFIX}_`)) {
    return humanizeIdentifier(stripKnownPrefix(normalized, ["dmp"]));
  }

  const parts = stripKnownPrefix(normalized, [ENERGY_MODEL_PREFIX]).split("_").filter(Boolean);
  if (parts.length < 2) return humanizeIdentifier(name);

  const metric = parts[parts.length - 1];
  const locationParts = parts.slice(0, -1);
  return `Energy Prediction - ${humanizeIdentifier(locationParts.join("_"))} - ${humanizeIdentifier(metric)}`;
}
