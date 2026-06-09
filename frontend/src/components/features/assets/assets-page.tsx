"use client";

import { useEffect, useMemo, useState } from "react";
import { Icon } from "@/components/common/icons";
import { Card, Field } from "@/components/common/primitives";
import {
  createBuilding,
  createMetric,
  createSite,
  getDevices,
  getLocationOptions,
  getMetricOptions,
  registerDevice,
  updateDevice,
  updateLocation,
  updateMetric,
  type DeviceOption,
  type LocationOption,
  type MetricOption,
} from "@/lib/models-api";

function parseMetadata(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return null;
  return JSON.parse(trimmed) as Record<string, unknown>;
}

function csvList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function AssetsPage() {
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [metrics, setMetrics] = useState<MetricOption[]>([]);
  const [devices, setDevices] = useState<DeviceOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [siteId, setSiteId] = useState("");
  const [siteName, setSiteName] = useState("");
  const [siteMetadata, setSiteMetadata] = useState("");

  const [buildingId, setBuildingId] = useState("");
  const [buildingName, setBuildingName] = useState("");
  const [buildingSiteId, setBuildingSiteId] = useState("");
  const [buildingMetadata, setBuildingMetadata] = useState("");

  const [locationQuery, setLocationQuery] = useState("");
  const [deviceQuery, setDeviceQuery] = useState("");

  const [metricId, setMetricId] = useState("");
  const [metricUnit, setMetricUnit] = useState("");
  const [metricDescription, setMetricDescription] = useState("");
  const [editMetricId, setEditMetricId] = useState("");
  const [editMetricUnit, setEditMetricUnit] = useState("");
  const [editMetricDescription, setEditMetricDescription] = useState("");

  const [deviceId, setDeviceId] = useState("");
  const [deviceBuildingId, setDeviceBuildingId] = useState("");
  const [deviceTypeId, setDeviceTypeId] = useState("virtual_meter");
  const [deviceMetrics, setDeviceMetrics] = useState("");
  const [locationStatusFilter, setLocationStatusFilter] = useState<"all" | "active" | "archived">("all");
  const [deviceStatusFilter, setDeviceStatusFilter] = useState<"all" | "active" | "inactive">("all");

  const siteOptions = useMemo(() => locations.filter((location) => !location.parent_id && !location.archived), [locations]);
  const buildingOptions = useMemo(() => locations.filter((location) => location.parent_id && !location.archived), [locations]);
  const filteredLocations = useMemo(() => {
    const query = locationQuery.trim().toLowerCase();
    return locations.filter((location) => {
      if (locationStatusFilter === "active" && location.archived) return false;
      if (locationStatusFilter === "archived" && !location.archived) return false;
      if (!query) return true;
      return [location.id, location.name, location.location_type, location.parent_id ?? "", location.archived ? "archived" : "active"]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [locationQuery, locationStatusFilter, locations]);
  const filteredDevices = useMemo(() => {
    const query = deviceQuery.trim().toLowerCase();
    return devices.filter((device) => {
      if (deviceStatusFilter === "active" && device.status !== "Active") return false;
      if (deviceStatusFilter === "inactive" && device.status !== "Inactive") return false;
      if (!query) return true;
      return [device.id, device.building_id, device.device_type_id, device.status, device.metric_type_ids.join(" ")]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [deviceQuery, devices, deviceStatusFilter]);
  const locationNotFound = Boolean(locationQuery.trim() && filteredLocations.length === 0);
  const deviceNotFound = Boolean(deviceQuery.trim() && filteredDevices.length === 0);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [locationData, metricData, deviceData] = await Promise.all([
        getLocationOptions({ includeArchived: true, limit: 200 }),
        getMetricOptions(),
        getDevices({ limit: 200 }),
      ]);
      setLocations(locationData.locations);
      setMetrics(metricData.metrics);
      setDevices(deviceData.devices);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load asset data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void refresh();
    }, 0);

    return () => window.clearTimeout(timeout);
  }, []);

  async function run(action: string, fn: () => Promise<string>) {
    setSubmitting(action);
    setError(null);
    setMessage(null);
    try {
      const nextMessage = await fn();
      setMessage(nextMessage);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed.");
    } finally {
      setSubmitting(null);
    }
  }

  function resetSiteForm() {
    setSiteId("");
    setSiteName("");
    setSiteMetadata("");
  }

  function resetBuildingForm() {
    setBuildingId("");
    setBuildingName("");
    setBuildingSiteId("");
    setBuildingMetadata("");
  }

  function resetMetricForm() {
    setMetricId("");
    setMetricUnit("");
    setMetricDescription("");
  }

  function resetDeviceForm() {
    setDeviceId("");
    setDeviceBuildingId("");
    setDeviceTypeId("virtual_meter");
    setDeviceMetrics("");
  }

  async function toggleLocationArchive(location: LocationOption) {
    const nextArchived = !location.archived;
    const action = `archive-${location.id}`;
    setSubmitting(action);
    setError(null);
    setMessage(null);
    try {
      const updated = await updateLocation(location.id, { archived: nextArchived });
      setLocations((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setMessage(`Location ${location.id} ${nextArchived ? "archived" : "restored"}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update location.");
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <main className="page assets-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Sites & Meters</h1>
          <p className="page-sub">Manage locations, metrics, and meter capability records used by training validation.</p>
        </div>
        <button className="btn" type="button" onClick={refresh} disabled={loading}>
          <Icon name={loading ? "refresh" : "search"} className={loading ? "spin" : undefined} />
          <span>{loading ? "Loading..." : "Refresh"}</span>
        </button>
      </div>

      {error && <div className="anomaly-error">{error}</div>}
      {message && <div className="models-success">{message}</div>}

      <div className="grid assets-grid">
        <Card
          title="Create Site"
          sub="Top-level location"
          icon="map"
          actions={
            <button
              className="btn btn-primary"
              type="button"
              disabled={submitting === "site"}
              onClick={() =>
                run("site", async () => {
                  await createSite({ id: siteId, name: siteName, metadata: parseMetadata(siteMetadata) });
                  resetSiteForm();
                  return `Site ${siteId} created.`;
                })
              }
            >
              <Icon name={submitting === "site" ? "refresh" : "plus"} className={submitting === "site" ? "spin" : undefined} />
              <span>Create</span>
            </button>
          }
        >
          <div className="asset-form">
            <Field label="Site ID">
              <input className="input" value={siteId} onChange={(event) => setSiteId(event.target.value)} placeholder="Panther_campus" />
            </Field>
            <Field label="Name">
              <input className="input" value={siteName} onChange={(event) => setSiteName(event.target.value)} placeholder="Panther Campus" />
            </Field>
            <Field label="Metadata JSON">
              <textarea className="textarea" value={siteMetadata} onChange={(event) => setSiteMetadata(event.target.value)} placeholder='{"timezone":"UTC"}' />
            </Field>
          </div>
        </Card>

        <Card
          title="Create Building"
          sub="Building under a site"
          icon="building"
          actions={
            <button
              className="btn btn-primary"
              type="button"
              disabled={submitting === "building"}
              onClick={() =>
                run("building", async () => {
                  await createBuilding({ id: buildingId, site_id: buildingSiteId, name: buildingName, metadata: parseMetadata(buildingMetadata) });
                  resetBuildingForm();
                  return `Building ${buildingId} created.`;
                })
              }
            >
              <Icon name={submitting === "building" ? "refresh" : "plus"} className={submitting === "building" ? "spin" : undefined} />
              <span>Create</span>
            </button>
          }
        >
          <div className="asset-form">
            <Field label="Building ID">
              <input className="input" value={buildingId} onChange={(event) => setBuildingId(event.target.value)} placeholder="Panther_lodging_Cora" />
            </Field>
            <Field label="Site">
              <select className="input" value={buildingSiteId} onChange={(event) => setBuildingSiteId(event.target.value)}>
                <option value="">Select site</option>
                {siteOptions.map((site) => (
                  <option value={site.id} key={site.id}>{site.id}</option>
                ))}
              </select>
            </Field>
            <Field label="Name">
              <input className="input" value={buildingName} onChange={(event) => setBuildingName(event.target.value)} />
            </Field>
            <Field label="Metadata JSON">
              <textarea className="textarea" value={buildingMetadata} onChange={(event) => setBuildingMetadata(event.target.value)} />
            </Field>
          </div>
        </Card>

        <Card title="Metrics" sub="Create or update metric types" icon="sliders">
          <div className="asset-form">
            <Field label="Metric ID">
              <input className="input" value={metricId} onChange={(event) => setMetricId(event.target.value)} placeholder="temperature" />
            </Field>
            <Field label="Unit">
              <input className="input" value={metricUnit} onChange={(event) => setMetricUnit(event.target.value)} placeholder="degC" />
            </Field>
            <Field label="Description">
              <input className="input" value={metricDescription} onChange={(event) => setMetricDescription(event.target.value)} />
            </Field>
            <button
              className="btn btn-primary"
              type="button"
              disabled={submitting === "metric"}
              onClick={() =>
                run("metric", async () => {
                  await createMetric({ id: metricId, unit: metricUnit || null, description: metricDescription || null });
                  resetMetricForm();
                  return `Metric ${metricId} created.`;
                })
              }
            >
              <Icon name={submitting === "metric" ? "refresh" : "plus"} className={submitting === "metric" ? "spin" : undefined} />
              <span>Create Metric</span>
            </button>
            <Field label="Edit Existing Metric">
              <select
                className="input"
                value={editMetricId}
                onChange={(event) => {
                  const metric = metrics.find((item) => item.id === event.target.value);
                  setEditMetricId(event.target.value);
                  setEditMetricUnit(metric?.unit ?? "");
                  setEditMetricDescription(metric?.description ?? "");
                }}
              >
                <option value="">Select metric</option>
                {metrics.map((metric) => (
                  <option value={metric.id} key={metric.id}>{metric.id}</option>
                ))}
              </select>
            </Field>
            <Field label="Updated Unit">
              <input className="input" value={editMetricUnit} onChange={(event) => setEditMetricUnit(event.target.value)} />
            </Field>
            <Field label="Updated Description">
              <input className="input" value={editMetricDescription} onChange={(event) => setEditMetricDescription(event.target.value)} />
            </Field>
            <button
              className="btn"
              type="button"
              disabled={!editMetricId || submitting === "metric-update"}
              onClick={() =>
                run("metric-update", async () => {
                  await updateMetric(editMetricId, { unit: editMetricUnit || null, description: editMetricDescription || null });
                  return `Metric ${editMetricId} updated.`;
                })
              }
            >
              <Icon name={submitting === "metric-update" ? "refresh" : "check"} className={submitting === "metric-update" ? "spin" : undefined} />
              <span>Update Metric</span>
            </button>
          </div>
        </Card>

        <Card title="Register Meter" sub="Device capability record" icon="wifi">
          <div className="asset-form">
            <Field label="Device ID">
              <input className="input" value={deviceId} onChange={(event) => setDeviceId(event.target.value)} placeholder="meter_temperature_building_a" />
            </Field>
            <Field label="Building">
              <select className="input" value={deviceBuildingId} onChange={(event) => setDeviceBuildingId(event.target.value)}>
                <option value="">Select building</option>
                {buildingOptions.map((building) => (
                  <option value={building.id} key={building.id}>{building.id}</option>
                ))}
              </select>
            </Field>
            <Field label="Device Type">
              <input className="input" value={deviceTypeId} onChange={(event) => setDeviceTypeId(event.target.value)} />
            </Field>
            <Field label="Metric IDs">
              <input className="input" value={deviceMetrics} onChange={(event) => setDeviceMetrics(event.target.value)} placeholder="electricity,temperature" />
            </Field>
            <button
              className="btn btn-primary"
              type="button"
              disabled={submitting === "device"}
              onClick={() =>
                run("device", async () => {
                  await registerDevice({
                    id: deviceId,
                    building_id: deviceBuildingId,
                    device_type_id: deviceTypeId,
                    metric_type_ids: csvList(deviceMetrics),
                  });
                  resetDeviceForm();
                  return `Device ${deviceId} registered.`;
                })
              }
            >
              <Icon name={submitting === "device" ? "refresh" : "plus"} className={submitting === "device" ? "spin" : undefined} />
              <span>Register</span>
            </button>
          </div>
        </Card>

        <Card title="Locations" sub={`${filteredLocations.length} of ${locations.length} records`} icon="table">
          <div className="asset-query">
            <input
              className="input"
              list="location-options"
              value={locationQuery}
              onChange={(event) => setLocationQuery(event.target.value)}
              placeholder="Query location by ID, name, type, or status"
            />
            <datalist id="location-options">
              {locations.map((location) => (
                <option value={location.id} key={location.id} />
              ))}
            </datalist>
            {locationNotFound && <div className="asset-inline-error">Location does not exist.</div>}
            <div className="asset-filter-row" aria-label="Location status filter">
              {(["all", "active", "archived"] as const).map((status) => (
                <button
                  className={locationStatusFilter === status ? "is-selected" : ""}
                  type="button"
                  key={status}
                  onClick={() => setLocationStatusFilter(status)}
                >
                  <span>{status === "all" ? "All" : status === "active" ? "Active" : "Archived"}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="asset-list">
            {filteredLocations.map((location) => (
              <div className="asset-row" key={location.id}>
                <div>
                  <b>{location.id}</b>
                  <span>
                    {location.name}
                    {location.parent_id ? ` · ${location.parent_id}` : ""}
                  </span>
                </div>
                <div className="asset-badges">
                  <span className="badge badge-neutral">{location.location_type}</span>
                  {location.archived && <span className="badge badge-neutral">Archived</span>}
                  <button
                    className="btn btn-small"
                    type="button"
                    disabled={submitting === `archive-${location.id}`}
                    onClick={() => void toggleLocationArchive(location)}
                  >
                    {location.archived ? "Restore" : "Archive"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Devices" sub={`${filteredDevices.length} of ${devices.length} registered`} icon="table">
          <div className="asset-query">
            <input
              className="input"
              list="device-options"
              value={deviceQuery}
              onChange={(event) => setDeviceQuery(event.target.value)}
              placeholder="Query device by ID, building, metric, or status"
            />
            <datalist id="device-options">
              {devices.map((device) => (
                <option value={device.id} key={device.id} />
              ))}
            </datalist>
            {deviceNotFound && <div className="asset-inline-error">Device does not exist.</div>}
            <div className="asset-filter-row" aria-label="Device status filter">
              {(["all", "active", "inactive"] as const).map((status) => (
                <button
                  className={deviceStatusFilter === status ? "is-selected" : ""}
                  type="button"
                  key={status}
                  onClick={() => setDeviceStatusFilter(status)}
                >
                  <span>{status === "all" ? "All" : status === "active" ? "Active" : "Inactive"}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="asset-list">
            {filteredDevices.map((device) => (
              <div className="asset-row" key={device.id}>
                <div>
                  <b>{device.id}</b>
                  <span>{device.building_id}</span>
                </div>
                <div className="asset-badges">
                  <span className="badge badge-neutral">{device.status}</span>
                  <span className="badge badge-neutral">{device.metric_type_ids.join(", ") || "No metrics"}</span>
                  <button
                    className="btn btn-small"
                    type="button"
                    disabled={submitting === `status-${device.id}`}
                    onClick={() =>
                      run(`status-${device.id}`, async () => {
                        const nextStatus = device.status === "Inactive" ? "Active" : "Inactive";
                        await updateDevice(device.id, { status: nextStatus });
                        return `Device ${device.id} ${nextStatus === "Active" ? "activated" : "deactivated"}.`;
                      })
                    }
                  >
                    {device.status === "Inactive" ? "Activate" : "Deactivate"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </main>
  );
}
