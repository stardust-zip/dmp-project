"use client";

import { useEffect, useMemo, useState } from "react";
import { Icon } from "@/components/common/icons";
import { Card, Field, Segmented } from "@/components/common/primitives";
import {
  createBuilding,
  createMetric,
  createSite,
  getDevices,
  getLocationOptions,
  getMetricOptions,
  getRegisteredModels,
  registerDevice,
  updateDevice,
  updateLocation,
  updateMetric,
  type DeviceOption,
  type LocationOption,
  type MetricOption,
  type RegisteredModel,
} from "@/lib/models-api";

type GalleryMode = "locations" | "devices";
type LocationFilter = "all" | "active" | "archived";
type DeviceFilter = "all" | "active" | "inactive";
type AssetModal = "site" | "building" | "device" | null;
type DetailTarget = { kind: "location"; item: LocationOption } | { kind: "device"; item: DeviceOption } | null;

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

function titleCase(value?: string | null) {
  if (!value) return "Unspecified";
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function shortJson(value?: Record<string, unknown> | null) {
  if (!value || Object.keys(value).length === 0) return "No metadata";
  return JSON.stringify(value, null, 2);
}

function modelMatches(model: RegisteredModel, terms: string[]) {
  const haystack = [
    model.name,
    model.description ?? "",
    model.production_version?.run_id ?? "",
    ...Object.entries(model.tags ?? {}).flatMap(([key, value]) => [key, value]),
  ]
    .join(" ")
    .toLowerCase();

  return terms.some((term) => term && haystack.includes(term.toLowerCase()));
}

export function AssetsPage() {
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [metrics, setMetrics] = useState<MetricOption[]>([]);
  const [devices, setDevices] = useState<DeviceOption[]>([]);
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [galleryMode, setGalleryMode] = useState<GalleryMode>("locations");
  const [activeModal, setActiveModal] = useState<AssetModal>(null);
  const [detailTarget, setDetailTarget] = useState<DetailTarget>(null);

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
  const [locationStatusFilter, setLocationStatusFilter] = useState<LocationFilter>("all");
  const [deviceStatusFilter, setDeviceStatusFilter] = useState<DeviceFilter>("all");

  const siteOptions = useMemo(() => locations.filter((location) => !location.parent_id && !location.archived), [locations]);
  const buildingOptions = useMemo(() => locations.filter((location) => location.parent_id && !location.archived), [locations]);
  const buildingById = useMemo(() => new Map(buildingOptions.map((location) => [location.id, location])), [buildingOptions]);
  const locationById = useMemo(() => new Map(locations.map((location) => [location.id, location])), [locations]);

  const activeLocationCount = useMemo(() => locations.filter((location) => !location.archived).length, [locations]);
  const activeDeviceCount = useMemo(() => devices.filter((device) => device.status === "Active").length, [devices]);

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

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [locationData, metricData, deviceData, modelData] = await Promise.all([
        getLocationOptions({ includeArchived: true, limit: 200 }),
        getMetricOptions(),
        getDevices({ limit: 200 }),
        getRegisteredModels(),
      ]);
      setLocations(locationData.locations);
      setMetrics(metricData.metrics);
      setDevices(deviceData.devices);
      setModels(modelData.models);
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

  useEffect(() => {
    const query = locationQuery.trim();
    if (!query) return;

    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      try {
        const data = await getLocationOptions({ q: query, includeArchived: true, limit: 200 }, controller.signal);
        setLocations((current) => {
          const merged = new Map(current.map((location) => [location.id, location]));
          data.locations.forEach((location) => merged.set(location.id, location));
          return Array.from(merged.values());
        });
      } catch {
        // The local filter still works if the remote search is cancelled or unavailable.
      }
    }, 250);

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [locationQuery]);

  async function run(action: string, fn: () => Promise<string>) {
    setSubmitting(action);
    setError(null);
    setMessage(null);
    try {
      const nextMessage = await fn();
      setMessage(nextMessage);
      await refresh();
      setActiveModal(null);
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

  function modelsForLocation(location: LocationOption) {
    const childIds = locations.filter((item) => item.parent_id === location.id).map((item) => item.id);
    return models.filter((model) => modelMatches(model, [location.id, location.name, location.parent_id ?? "", ...childIds]));
  }

  function modelsForDevice(device: DeviceOption) {
    const building = buildingById.get(device.building_id);
    const site = building?.parent_id ? locationById.get(building.parent_id) : null;
    return models.filter((model) => modelMatches(model, [device.id, device.building_id, building?.name ?? "", site?.id ?? "", ...device.metric_type_ids]));
  }

  const selectedLocation = detailTarget?.kind === "location" ? detailTarget.item : null;
  const selectedDevice = detailTarget?.kind === "device" ? detailTarget.item : null;

  return (
    <main className="page assets-page">
      <div className="page-head assets-head">
        <div>
          <h1 className="page-title">Assets Management</h1>
          <p className="page-sub">Admin workspace for site hierarchy, building inventory, meters, metadata, and model coverage.</p>
        </div>
        <div className="page-head-actions asset-primary-actions">
          <button className="btn" type="button" onClick={refresh} disabled={loading}>
            <Icon name="refresh" className={loading ? "spin" : undefined} />
            <span>{loading ? "Loading..." : "Refresh"}</span>
          </button>
          <button className="btn btn-primary" type="button" onClick={() => setActiveModal("site")}>
            <Icon name="map" />
            <span>Create Site</span>
          </button>
          <button className="btn btn-primary" type="button" onClick={() => setActiveModal("building")}>
            <Icon name="building" />
            <span>Create Building</span>
          </button>
          <button className="btn btn-primary" type="button" onClick={() => setActiveModal("device")}>
            <Icon name="wifi" />
            <span>Register Meter</span>
          </button>
        </div>
      </div>

      {error && <div className="anomaly-error">{error}</div>}
      {message && <div className="models-success">{message}</div>}

      <section className="asset-summary-grid">
        <div className="asset-summary-card">
          <span className="asset-summary-label">Locations</span>
          <b className="asset-summary-value">{locations.length}</b>
          <small className="asset-summary-foot">{activeLocationCount} active</small>
        </div>
        <div className="asset-summary-card">
          <span className="asset-summary-label">Registered meters</span>
          <b className="asset-summary-value">{devices.length}</b>
          <small className="asset-summary-foot">{activeDeviceCount} active</small>
        </div>
        <div className="asset-summary-card">
          <span className="asset-summary-label">Metric catalog</span>
          <b className="asset-summary-value">{metrics.length}</b>
          <small className="asset-summary-foot">{models.length} models indexed</small>
        </div>
      </section>

      <div className="assets-layout">
        <Card title="Asset Gallery" sub={galleryMode === "locations" ? `${filteredLocations.length} locations shown` : `${filteredDevices.length} devices shown`} icon={galleryMode === "locations" ? "map" : "wifi"}>
          <div className="asset-toolbar">
            <Segmented
              value={galleryMode}
              options={[
                { value: "locations", label: "Locations" },
                { value: "devices", label: "Devices" },
              ]}
              onChange={setGalleryMode}
            />
            {galleryMode === "locations" ? (
              <>
                <div className="asset-search">
                  <Icon name="search" />
                  <input value={locationQuery} onChange={(event) => setLocationQuery(event.target.value)} placeholder="Search location, parent, type, status" />
                </div>
                <div className="asset-filter-row" aria-label="Location status filter">
                  {(["all", "active", "archived"] as const).map((status) => (
                    <button className={locationStatusFilter === status ? "is-selected" : ""} type="button" key={status} onClick={() => setLocationStatusFilter(status)}>
                      {status === "all" ? "All" : status === "active" ? "Active" : "Archived"}
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <>
                <div className="asset-search">
                  <Icon name="search" />
                  <input value={deviceQuery} onChange={(event) => setDeviceQuery(event.target.value)} placeholder="Search device, building, metric, status" />
                </div>
                <div className="asset-filter-row" aria-label="Device status filter">
                  {(["all", "active", "inactive"] as const).map((status) => (
                    <button className={deviceStatusFilter === status ? "is-selected" : ""} type="button" key={status} onClick={() => setDeviceStatusFilter(status)}>
                      {status === "all" ? "All" : status === "active" ? "Active" : "Inactive"}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          {galleryMode === "locations" ? (
            <div className="asset-gallery">
              {filteredLocations.map((location) => {
                const childBuildings = locations.filter((item) => item.parent_id === location.id);
                const attachedDevices = devices.filter((device) => device.building_id === location.id || childBuildings.some((building) => building.id === device.building_id));
                const matchedModels = modelsForLocation(location);
                return (
                  <button className="asset-tile" type="button" key={location.id} onClick={() => setDetailTarget({ kind: "location", item: location })}>
                    <div className="asset-tile-head">
                      <span className="asset-tile-icon"><Icon name={location.parent_id ? "building" : "map"} /></span>
                      <span className={`badge ${location.archived ? "badge-neutral" : "badge-resolved"}`}>{location.archived ? "Archived" : "Active"}</span>
                    </div>
                    <b>{location.name || location.id}</b>
                    <span>{location.id}</span>
                    <div className="asset-tile-meta">
                      <small>{titleCase(location.location_type)}</small>
                      <small>{location.parent_id ? `Parent ${location.parent_id}` : "Top-level site"}</small>
                    </div>
                    <div className="asset-tile-stats">
                      {/*<span>{childBuildings.length} buildings</span>
                      <span>{attachedDevices.length} meters</span>
                      <span>{matchedModels.length} models</span>*/}
                      <span>No info yet</span>
                    </div>
                  </button>
                );
              })}
              {filteredLocations.length === 0 && <div className="asset-empty">No locations match the selected filters.</div>}
            </div>
          ) : (
            <div className="asset-gallery">
              {filteredDevices.map((device) => {
                const building = buildingById.get(device.building_id);
                const matchedModels = modelsForDevice(device);
                return (
                  <button className="asset-tile" type="button" key={device.id} onClick={() => setDetailTarget({ kind: "device", item: device })}>
                    <div className="asset-tile-head">
                      <span className="asset-tile-icon"><Icon name="wifi" /></span>
                      <span className={`badge ${device.status === "Active" ? "badge-resolved" : "badge-neutral"}`}>{device.status}</span>
                    </div>
                    <b>{device.id}</b>
                    <span>{building?.name ?? device.building_id}</span>
                    <div className="asset-tile-meta">
                      <small>{titleCase(device.device_type_id)}</small>
                      <small>{device.metric_type_ids.length} metrics</small>
                    </div>
                    <div className="asset-tile-stats">
                      <span>{device.metric_type_ids.slice(0, 2).join(", ") || "No metrics"}</span>
                      <span>{matchedModels.length} models</span>
                    </div>
                  </button>
                );
              })}
              {filteredDevices.length === 0 && <div className="asset-empty">No devices match the selected filters.</div>}
            </div>
          )}
        </Card>

        <Card title="Metric Catalog" sub="Create and update trainable signals" icon="sliders">
          <div className="asset-form compact">
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
            <Field label="Edit Metric">
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
      </div>

      {activeModal && (
        <>
          <button className="overlay" type="button" aria-label="Close dialog" onClick={() => setActiveModal(null)} />
          <div className="asset-modal" role="dialog" aria-modal="true" aria-label={activeModal}>
            <div className="model-modal-head">
              <div>
                <h2>{activeModal === "site" ? "Create Site" : activeModal === "building" ? "Create Building" : "Register Meter"}</h2>
                <span>{activeModal === "site" ? "Add a top-level location." : activeModal === "building" ? "Attach a building to a site." : "Register a device capability record."}</span>
              </div>
              <button className="icon-btn" type="button" aria-label="Close dialog" onClick={() => setActiveModal(null)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="model-modal-body">
              {activeModal === "site" && (
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
                    <span>Create Site</span>
                  </button>
                </div>
              )}
              {activeModal === "building" && (
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
                    <span>Create Building</span>
                  </button>
                </div>
              )}
              {activeModal === "device" && (
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
                    <span>Register Meter</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {detailTarget && (
        <>
          <button className="overlay" type="button" aria-label="Close details" onClick={() => setDetailTarget(null)} />
          <aside className="drawer asset-detail" role="dialog" aria-label="Asset details">
            <div className="drawer-head">
              <div>
                <h3>{selectedLocation?.name ?? selectedDevice?.id}</h3>
                <span>{detailTarget.kind === "location" ? "Location metadata and model usage" : "Device registration and model usage"}</span>
              </div>
              <button className="icon-btn" type="button" aria-label="Close details" onClick={() => setDetailTarget(null)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="drawer-body">
              {selectedLocation && (
                <>
                  <div className="sec-label">Metadata</div>
                  <dl className="dl">
                    <dt>ID</dt><dd>{selectedLocation.id}</dd>
                    <dt>Name</dt><dd>{selectedLocation.name}</dd>
                    <dt>Type</dt><dd>{titleCase(selectedLocation.location_type)}</dd>
                    <dt>Parent</dt><dd>{selectedLocation.parent_id ?? "Top-level site"}</dd>
                    <dt>Status</dt><dd>{selectedLocation.archived ? "Archived" : "Active"}</dd>
                  </dl>
                  <pre className="asset-json">{shortJson(selectedLocation.metadata)}</pre>
                  <div className="sec-label">Related Assets</div>
                  <div className="asset-detail-list">
                    {locations.filter((item) => item.parent_id === selectedLocation.id).map((item) => <span key={item.id}>{item.name || item.id}</span>)}
                    {devices.filter((device) => device.building_id === selectedLocation.id).map((device) => <span key={device.id}>{device.id}</span>)}
                    {locations.filter((item) => item.parent_id === selectedLocation.id).length === 0 && devices.filter((device) => device.building_id === selectedLocation.id).length === 0 && <span>No direct children</span>}
                  </div>
                  <div className="sec-label">Model Usage</div>
                  <div className="asset-detail-list">
                    {modelsForLocation(selectedLocation).map((model) => <span key={model.name}>{model.name}</span>)}
                    {modelsForLocation(selectedLocation).length === 0 && <span>No matching model tags or names found</span>}
                  </div>
                </>
              )}
              {selectedDevice && (
                <>
                  <div className="sec-label">Registration</div>
                  <dl className="dl">
                    <dt>ID</dt><dd>{selectedDevice.id}</dd>
                    <dt>Building</dt><dd>{selectedDevice.building_id}</dd>
                    <dt>Type</dt><dd>{titleCase(selectedDevice.device_type_id)}</dd>
                    <dt>Status</dt><dd>{selectedDevice.status}</dd>
                    <dt>Metrics</dt><dd>{selectedDevice.metric_type_ids.join(", ") || "No metrics"}</dd>
                  </dl>
                  <div className="sec-label">Metric Definitions</div>
                  <div className="asset-detail-list">
                    {selectedDevice.metric_type_ids.map((metricId) => {
                      const metric = metrics.find((item) => item.id === metricId);
                      return <span key={metricId}>{metricId}{metric?.unit ? ` (${metric.unit})` : ""}{metric?.description ? ` - ${metric.description}` : ""}</span>;
                    })}
                    {selectedDevice.metric_type_ids.length === 0 && <span>No metric capabilities recorded</span>}
                  </div>
                  <div className="sec-label">Model Usage</div>
                  <div className="asset-detail-list">
                    {modelsForDevice(selectedDevice).map((model) => <span key={model.name}>{model.name}</span>)}
                    {modelsForDevice(selectedDevice).length === 0 && <span>No matching model tags or names found</span>}
                  </div>
                </>
              )}
            </div>
            <div className="drawer-foot">
              {selectedLocation && (
                <button className="btn btn-primary" type="button" disabled={submitting === `archive-${selectedLocation.id}`} onClick={() => void toggleLocationArchive(selectedLocation)}>
                  <Icon name="flag" />
                  <span>{selectedLocation.archived ? "Restore Location" : "Archive Location"}</span>
                </button>
              )}
              {selectedDevice && (
                <button
                  className="btn btn-primary"
                  type="button"
                  disabled={submitting === `status-${selectedDevice.id}`}
                  onClick={() =>
                    run(`status-${selectedDevice.id}`, async () => {
                      const nextStatus = selectedDevice.status === "Inactive" ? "Active" : "Inactive";
                      await updateDevice(selectedDevice.id, { status: nextStatus });
                      setDetailTarget(null);
                      return `Device ${selectedDevice.id} ${nextStatus === "Active" ? "activated" : "deactivated"}.`;
                    })
                  }
                >
                  <Icon name="check" />
                  <span>{selectedDevice.status === "Inactive" ? "Activate Device" : "Deactivate Device"}</span>
                </button>
              )}
            </div>
          </aside>
        </>
      )}
    </main>
  );
}
