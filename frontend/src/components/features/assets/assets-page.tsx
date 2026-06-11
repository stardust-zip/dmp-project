"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Icon } from "@/components/common/icons";
import { Card, Field } from "@/components/common/primitives";
import { displayLocationName, displayModelName, humanizeIdentifier, isSiteLocation, locationSearchText } from "@/lib/format";
import {
  createBuilding,
  createMetric,
  createSite,
  getLocationOptions,
  getMetricOptions,
  getRegisteredModels,
  updateLocation,
  updateMetric,
  type LocationOption,
  type MetricOption,
  type RegisteredModel,
} from "@/lib/models-api";

type LocationFilter = "all" | "active" | "archived";
type AssetModal = "site" | "building" | null;
type DetailTarget = { kind: "location"; item: LocationOption } | null;

const LOCATION_INDEX_LIMIT = 1000;
const LOCATIONS_PER_PAGE = 24;

function parseMetadata(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return null;
  return JSON.parse(trimmed) as Record<string, unknown>;
}

function titleCase(value?: string | null) {
  return humanizeIdentifier(value);
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
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
  const [searchedLocations, setSearchedLocations] = useState<LocationOption[] | null>(null);
  const [locationSearchLoading, setLocationSearchLoading] = useState(false);

  const [metricId, setMetricId] = useState("");
  const [metricUnit, setMetricUnit] = useState("");
  const [metricDescription, setMetricDescription] = useState("");
  const [editMetricId, setEditMetricId] = useState("");
  const [editMetricUnit, setEditMetricUnit] = useState("");
  const [editMetricDescription, setEditMetricDescription] = useState("");

  const [locationStatusFilter, setLocationStatusFilter] = useState<LocationFilter>("all");
  const [locationPage, setLocationPage] = useState(1);

  const siteOptions = useMemo(() => locations.filter((location) => isSiteLocation(location) && !location.archived), [locations]);
  const locationById = useMemo(() => new Map(locations.map((location) => [location.id, location])), [locations]);

  const activeLocationCount = useMemo(() => locations.filter((location) => !location.archived).length, [locations]);
  const archivedLocationCount = locations.length - activeLocationCount;
  const locationSource = locationQuery.trim() && searchedLocations ? searchedLocations : locations;

  const filteredLocations = useMemo(() => {
    const query = locationQuery.trim().toLowerCase();
    return locationSource.filter((location) => {
      if (locationStatusFilter === "active" && location.archived) return false;
      if (locationStatusFilter === "archived" && !location.archived) return false;
      if (!query) return true;
      return `${locationSearchText(location, location.parent_id ? locationById.get(location.parent_id) : undefined)} ${location.archived ? "archived" : "active"}`.includes(query);
    });
  }, [locationById, locationQuery, locationSource, locationStatusFilter]);
  const totalLocationPages = Math.max(1, Math.ceil(filteredLocations.length / LOCATIONS_PER_PAGE));
  const safeLocationPage = Math.min(locationPage, totalLocationPages);
  const pagedLocations = useMemo(
    () => filteredLocations.slice((safeLocationPage - 1) * LOCATIONS_PER_PAGE, safeLocationPage * LOCATIONS_PER_PAGE),
    [filteredLocations, safeLocationPage],
  );
  const locationRangeStart = filteredLocations.length ? (safeLocationPage - 1) * LOCATIONS_PER_PAGE + 1 : 0;
  const locationRangeEnd = Math.min(safeLocationPage * LOCATIONS_PER_PAGE, filteredLocations.length);
  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [locationData, metricData, modelData] = await Promise.all([
        getLocationOptions({ includeArchived: true, limit: LOCATION_INDEX_LIMIT }),
        getMetricOptions(),
        getRegisteredModels(),
      ]);
      setLocations(locationData.locations);
      setMetrics(metricData.metrics);
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
    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      if (!query) {
        setSearchedLocations(null);
        setLocationSearchLoading(false);
        return;
      }

      setLocationSearchLoading(true);
      try {
        const data = await getLocationOptions({ q: query, includeArchived: true, limit: LOCATION_INDEX_LIMIT }, controller.signal);
        setSearchedLocations(data.locations);
      } catch {
        if (!controller.signal.aborted) setSearchedLocations([]);
      } finally {
        if (!controller.signal.aborted) setLocationSearchLoading(false);
      }
    }, query ? 180 : 0);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
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

  const modelsForLocation = useCallback((location: LocationOption) => {
    const childIds = locations.filter((item) => item.parent_id === location.id).map((item) => item.id);
    return models.filter((model) => modelMatches(model, [location.id, location.name, location.parent_id ?? "", ...childIds]));
  }, [locations, models]);

  const modelCoveredLocationCount = useMemo(
    () => locations.filter((location) => modelsForLocation(location).some((model) => model.production_version)).length,
    [locations, modelsForLocation],
  );

  const selectedLocation = detailTarget?.kind === "location" ? detailTarget.item : null;

  return (
    <main className="page assets-page">
      <div className="page-head assets-head">
        <div>
          <h1 className="page-title">Assets Management</h1>
          <p className="page-sub">Admin workspace for site hierarchy, building inventory, metadata, and model coverage.</p>
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
        </div>
      </div>

      {error && <div className="anomaly-error">{error}</div>}
      {message && <div className="models-success">{message}</div>}

      <section className="asset-summary-grid">
        <div className="asset-summary-card">
          <span className="asset-summary-label">Total locations</span>
          <b className="asset-summary-value">{locations.length}</b>
          <small className="asset-summary-foot">Loaded in local index</small>
        </div>
        <div className="asset-summary-card">
          <span className="asset-summary-label">Active locations</span>
          <b className="asset-summary-value">{activeLocationCount}</b>
          <small className="asset-summary-foot">Available in selectors</small>
        </div>
        <div className="asset-summary-card">
          <span className="asset-summary-label">Archived locations</span>
          <b className="asset-summary-value">{archivedLocationCount}</b>
          <small className="asset-summary-foot">Hidden from active workflows</small>
        </div>
        <div className="asset-summary-card">
          <span className="asset-summary-label">Model-covered locations</span>
          <b className="asset-summary-value">{modelCoveredLocationCount}</b>
          <small className="asset-summary-foot">Matched to production models</small>
        </div>
        <div className="asset-summary-card">
          <span className="asset-summary-label">Metric catalog</span>
          <b className="asset-summary-value">{metrics.length}</b>
          <small className="asset-summary-foot">{models.length} models indexed</small>
        </div>
      </section>

      <div className="assets-layout">
        <Card title="Location Gallery" sub={`${filteredLocations.length} of ${locations.length} locations found`} icon="map">
          <div className="asset-toolbar">
            <div className="asset-toolbar-controls">
              <div className="asset-search">
                <Icon name="search" />
                <input
                  value={locationQuery}
                  onChange={(event) => {
                    setLocationQuery(event.target.value);
                    setLocationPage(1);
                  }}
                  placeholder="Search location, parent, type, status"
                />
              </div>
              <div className="asset-filter-row" aria-label="Location status filter">
                {(["all", "active", "archived"] as const).map((status) => (
                  <button
                    className={locationStatusFilter === status ? "is-selected" : ""}
                    type="button"
                    key={status}
                    onClick={() => {
                      setLocationStatusFilter(status);
                      setLocationPage(1);
                    }}
                  >
                    {status === "all" ? "All" : status === "active" ? "Active" : "Archived"}
                  </button>
                ))}
              </div>
            </div>
            <span className="asset-search-help">
              {locationSearchLoading
                ? "Searching locations..."
                : locationQuery.trim()
                  ? `Found ${filteredLocations.length} locations for "${locationQuery.trim()}"`
                  : `${locations.length} locations loaded`}
            </span>
          </div>

          <div className="asset-gallery">
            {pagedLocations.map((location) => (
              <button className="asset-tile" type="button" key={location.id} onClick={() => setDetailTarget({ kind: "location", item: location })}>
                <div className="asset-tile-head">
                  <span className="asset-tile-icon"><Icon name={isSiteLocation(location) ? "map" : "building"} /></span>
                  <span className={`badge ${location.archived ? "badge-neutral" : "badge-resolved"}`}>{location.archived ? "Archived" : "Active"}</span>
                </div>
                <b title={location.name || location.id}>{displayLocationName(location.name, location.id)}</b>
                <span>{location.id}</span>
                <div className="asset-tile-meta">
                  <small>{titleCase(location.location_type)}</small>
                  <small>
                    {isSiteLocation(location)
                      ? "Site"
                      : location.parent_id
                        ? `Site ${location.parent_id}`
                        : "No site assigned"}
                  </small>
                </div>
                <div className="asset-tile-stats">
                  <span>{modelsForLocation(location).length} models</span>
                </div>
              </button>
            ))}
            {filteredLocations.length === 0 && <div className="asset-empty">No locations match the selected filters.</div>}
          </div>
          {filteredLocations.length > 0 && (
            <div className="pager">
              <span>
                Showing {locationRangeStart}-{locationRangeEnd} of {filteredLocations.length}
              </span>
              <div className="pager-btns">
                <button className="pg" type="button" disabled={safeLocationPage === 1} onClick={() => setLocationPage((current) => Math.max(1, current - 1))}>
                  <Icon name="chevLeft" style={{ width: 13, height: 13 }} />
                </button>
                {Array.from({ length: totalLocationPages }, (_, index) => index + 1)
                  .filter((page) => page === 1 || page === totalLocationPages || Math.abs(page - safeLocationPage) <= 1)
                  .map((page, index, pages) => (
                    <span key={page}>
                      {index > 0 && page - pages[index - 1] > 1 && <span className="muted" style={{ padding: "0 4px" }}>...</span>}
                      <button className={`pg ${safeLocationPage === page ? "on" : ""}`} type="button" onClick={() => setLocationPage(page)}>
                        {page}
                      </button>
                    </span>
                  ))}
                <button className="pg" type="button" disabled={safeLocationPage === totalLocationPages} onClick={() => setLocationPage((current) => Math.min(totalLocationPages, current + 1))}>
                  <Icon name="chevRight" style={{ width: 13, height: 13 }} />
                </button>
              </div>
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
                <h2>{activeModal === "site" ? "Create Site" : "Create Building"}</h2>
                <span>{activeModal === "site" ? "Add a top-level location." : "Attach a building to a site."}</span>
              </div>
              <button className="icon-btn" type="button" aria-label="Close dialog" onClick={() => setActiveModal(null)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="model-modal-body">
              {activeModal === "site" && (
                <div className="asset-form">
                  <Field label="Site ID">
                    <input className="input" value={siteId} onChange={(event) => setSiteId(event.target.value)} placeholder="Panther" />
                  </Field>
                  <Field label="Name">
                    <input className="input" value={siteName} onChange={(event) => setSiteName(event.target.value)} placeholder="Panther" />
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
                <h3>{selectedLocation ? displayLocationName(selectedLocation.name, selectedLocation.id) : ""}</h3>
                <span>Location metadata and model usage</span>
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
                    <dt>Name</dt><dd>{displayLocationName(selectedLocation.name, selectedLocation.id)}</dd>
                    <dt>Type</dt><dd>{titleCase(selectedLocation.location_type)}</dd>
                    <dt>Site</dt><dd>{isSiteLocation(selectedLocation) ? selectedLocation.id : selectedLocation.parent_id ?? "No site assigned"}</dd>
                    <dt>Status</dt><dd>{selectedLocation.archived ? "Archived" : "Active"}</dd>
                  </dl>
                  <pre className="asset-json">{shortJson(selectedLocation.metadata)}</pre>
                  <div className="sec-label">Related Assets</div>
                  <div className="asset-detail-list">
                    {locations.filter((item) => item.parent_id === selectedLocation.id).map((item) => <span key={item.id} title={item.id}>{displayLocationName(item.name, item.id)}</span>)}
                    {locations.filter((item) => item.parent_id === selectedLocation.id).length === 0 && <span>No direct child locations</span>}
                  </div>
                  <div className="sec-label">Model Usage</div>
                  <div className="asset-detail-list">
                    {modelsForLocation(selectedLocation).map((model) => <span key={model.name} title={model.name}>{displayModelName(model.name)}</span>)}
                    {modelsForLocation(selectedLocation).length === 0 && <span>No matching model tags or names found</span>}
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
            </div>
          </aside>
        </>
      )}
    </main>
  );
}
