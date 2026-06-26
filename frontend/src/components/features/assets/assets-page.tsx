"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Icon } from "@/components/common/icons";
import { Card, Field, FormMessage, Modal } from "@/components/common/primitives";
import { UserEditModal } from "@/components/features/users/user-edit-modal";
import { displayLocationName, humanizeIdentifier, isSiteLocation, locationSearchText } from "@/lib/format";
import {
  createBuilding,
  getLocationOptions,
  getRegisteredModels,
  type LocationOption,
  type RegisteredModel,
} from "@/lib/models-api";
import { getUsers, type ManagedUser, type ManagedUserStatus } from "@/lib/users-api";

type AssetModal = "building" | null;

const LOCATIONS_PER_PAGE = 8;
const BUILDINGS_PER_PAGE = 8;

type GeoPoint = {
  lat: number;
  lon: number;
};

type MappedLocation = {
  location: LocationOption;
  point: GeoPoint;
};

type AssignedOperator = {
  user: ManagedUser;
  assignment: "direct" | "site";
};

function parseMetadata(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return null;
  return JSON.parse(trimmed) as Record<string, unknown>;
}

function titleCase(value?: string | null) {
  return humanizeIdentifier(value);
}

function readNumber(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value.trim());
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function locationPoint(location?: LocationOption | null): GeoPoint | null {
  const metadata = location?.metadata;
  if (!metadata) return null;
  const lat = readNumber(metadata.latitude ?? metadata.lat);
  const lon = readNumber(metadata.longitude ?? metadata.longtitude ?? metadata.lon ?? metadata.lng);
  if (lat == null || lon == null) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return { lat, lon };
}

function statusLabel(status: ManagedUserStatus | string) {
  return humanizeIdentifier(status);
}

function operatorStatusTone(status: ManagedUserStatus | string) {
  if (status === "Available" || status === "In_Shift") return "user-status-available";
  if (status === "Busy" || status === "On_Break") return "user-status-busy";
  if (status === "Off_Duty" || status === "On_Leave") return "user-status-away";
  return "user-status-suspended";
}

function osmLocationUrl(point: GeoPoint, zoom = 18) {
  return `https://www.openstreetmap.org/?mlat=${point.lat}&mlon=${point.lon}#map=${zoom}/${point.lat}/${point.lon}`;
}

function osmEmbedUrl(point: GeoPoint, zoom = 17) {
  const delta = zoom >= 17 ? 0.004 : 0.02;
  const bbox = [point.lon - delta, point.lat - delta, point.lon + delta, point.lat + delta].map((value) => value.toFixed(6)).join("%2C");
  return `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${point.lat}%2C${point.lon}`;
}

function modelMatches(model: RegisteredModel, terms: string[]) {
  const lowerTerms = terms.filter(Boolean).map((t) => t.toLowerCase());
  if (!lowerTerms.length) return false;

  // If the model targets a specific building, require an exact match on that building.
  const tags = { ...(model.tags ?? {}), ...(model.production_version?.tags ?? {}) };
  const buildingId = tags.building_id?.toLowerCase();
  if (buildingId) {
    return lowerTerms.includes(buildingId);
  }
  const siteId = tags.site_id?.toLowerCase();
  if (siteId) {
    return lowerTerms.includes(siteId);
  }

  // Fall back to substring match on model name + metadata (global models, legacy).
  const haystack = [
    model.name,
    model.description ?? "",
    model.production_version?.run_id ?? "",
    model.production_version?.model_task ?? "",
    ...Object.entries(tags).flatMap(([key, value]) => [key, value]),
  ]
    .join(" ")
    .toLowerCase();

  return lowerTerms.some((term) => haystack.includes(term));
}

function modelTask(model: RegisteredModel) {
  const tags = model.tags ?? {};
  const taggedTask = model.production_version?.model_task || tags.model_task || tags.task || tags.type;
  if (taggedTask === "prediction" || taggedTask === "forecasting" || taggedTask === "anomaly_detection") return taggedTask;

  const text = `${model.name} ${model.description ?? ""}`.toLowerCase();
  if (text.includes("anomaly")) return "anomaly_detection";
  if (text.includes("forecast")) return "forecasting";
  if (text.includes("prediction") || text.includes("energy_prediction")) return "prediction";
  return "unknown";
}

function modelHasSpecificLocationScope(model: RegisteredModel) {
  const tags = { ...(model.tags ?? {}), ...(model.production_version?.tags ?? {}) };
  const hasValue = (v: string | undefined) => Boolean(v) && v!.toLowerCase() !== "none";
  return hasValue(tags.site_id) || hasValue(tags.building_id) || hasValue(tags.location_id);
}

function modelAppliesGlobally(model: RegisteredModel) {
  return Boolean(model.production_version) && !modelHasSpecificLocationScope(model);
}

export function AssetsPage() {
  const { session } = useAuth();
  const currentUser = session?.user;
  const canManageAssets = currentUser?.role === "Admin";
  const canViewModelCoverage = currentUser?.role === "Admin" || currentUser?.role === "AI_Engineer";
  const [locations, setLocations] = useState<LocationOption[]>([]);

  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [activeModal, setActiveModal] = useState<AssetModal>(null);
  const [editingOperator, setEditingOperator] = useState<ManagedUser | null>(null);
  const [assetFormError, setAssetFormError] = useState<string | null>(null);

  const [buildingId, setBuildingId] = useState("");
  const [buildingName, setBuildingName] = useState("");
  const [buildingSiteId, setBuildingSiteId] = useState("");
  const [buildingMetadata, setBuildingMetadata] = useState("");

  const [locationQuery, setLocationQuery] = useState("");
  const [buildingQuery, setBuildingQuery] = useState("");
  const [selectedLocationId, setSelectedLocationId] = useState<string | null>(null);
  const [activeSiteId, setActiveSiteId] = useState<string | null>(null);
  const [searchedLocations, setSearchedLocations] = useState<LocationOption[] | null>(null);
  const [locationSearchLoading, setLocationSearchLoading] = useState(false);

  const [locationPage, setLocationPage] = useState(1);
  const [buildingPage, setBuildingPage] = useState(1);

  const siteOptions = useMemo(() => locations.filter(isSiteLocation), [locations]);
  const locationById = useMemo(() => new Map(locations.map((location) => [location.id, location])), [locations]);

  const locationSource = locationQuery.trim() && searchedLocations ? searchedLocations : locations;
  const mappedLocations = useMemo<MappedLocation[]>(
    () => locations.map((location) => ({ location, point: locationPoint(location) })).filter((item): item is MappedLocation => item.point != null),
    [locations],
  );
  const mappedLocationById = useMemo(() => new Map(mappedLocations.map((item) => [item.location.id, item])), [mappedLocations]);
  const filteredLocations = useMemo(() => {
    const query = locationQuery.trim().toLowerCase();
    return locationSource.filter((location) => {
      if (!query) return true;
      return locationSearchText(location, location.parent_id ? locationById.get(location.parent_id) : undefined).includes(query);
    });
  }, [locationById, locationQuery, locationSource]);

  const buildingsBySiteId = useMemo(() => {
    const grouped = new Map<string, LocationOption[]>();
    for (const location of locations) {
      if (isSiteLocation(location) || !location.parent_id) continue;
      const buildings = grouped.get(location.parent_id) ?? [];
      buildings.push(location);
      grouped.set(location.parent_id, buildings);
    }
    return grouped;
  }, [locations]);

  const filteredSites = useMemo(() => {
    const query = locationQuery.trim();
    if (!query) return locations.filter(isSiteLocation);

    const matchingSiteIds = new Set<string>();
    for (const location of filteredLocations) {
      if (isSiteLocation(location)) {
        matchingSiteIds.add(location.id);
      } else if (location.parent_id) {
        matchingSiteIds.add(location.parent_id);
      }
    }
    return locations.filter((location) => isSiteLocation(location) && matchingSiteIds.has(location.id));
  }, [filteredLocations, locationQuery, locations]);

  const totalLocationPages = Math.max(1, Math.ceil(filteredSites.length / LOCATIONS_PER_PAGE));
  const safeLocationPage = Math.min(locationPage, totalLocationPages);
  const pagedSites = useMemo(
    () => filteredSites.slice((safeLocationPage - 1) * LOCATIONS_PER_PAGE, safeLocationPage * LOCATIONS_PER_PAGE),
    [filteredSites, safeLocationPage],
  );
  const activeSite = activeSiteId ? locationById.get(activeSiteId) ?? null : null;
  const activeSiteBuildings = useMemo(
    () => (activeSiteId ? buildingsBySiteId.get(activeSiteId) ?? [] : []),
    [activeSiteId, buildingsBySiteId],
  );
  const filteredActiveSiteBuildings = useMemo(() => {
    const query = buildingQuery.trim().toLowerCase();
    if (!query) return activeSiteBuildings;
    return activeSiteBuildings.filter((location) => locationSearchText(location, activeSite ?? undefined).includes(query));
  }, [activeSite, activeSiteBuildings, buildingQuery]);
  const totalBuildingPages = Math.max(1, Math.ceil(filteredActiveSiteBuildings.length / BUILDINGS_PER_PAGE));
  const safeBuildingPage = Math.min(buildingPage, totalBuildingPages);
  const pagedBuildings = useMemo(
    () => filteredActiveSiteBuildings.slice((safeBuildingPage - 1) * BUILDINGS_PER_PAGE, safeBuildingPage * BUILDINGS_PER_PAGE),
    [filteredActiveSiteBuildings, safeBuildingPage],
  );
  const selectedLocation = selectedLocationId ? locationById.get(selectedLocationId) ?? null : null;
  const selectedPoint = selectedLocation ? locationPoint(selectedLocation) : null;
  const locationRangeStart = filteredSites.length ? (safeLocationPage - 1) * LOCATIONS_PER_PAGE + 1 : 0;
  const locationRangeEnd = Math.min(safeLocationPage * LOCATIONS_PER_PAGE, filteredSites.length);
  const buildingRangeStart = filteredActiveSiteBuildings.length ? (safeBuildingPage - 1) * BUILDINGS_PER_PAGE + 1 : 0;
  const buildingRangeEnd = Math.min(safeBuildingPage * BUILDINGS_PER_PAGE, filteredActiveSiteBuildings.length);
  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    const errors: string[] = [];
    const errorMessage = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);
    const locationRequest = getLocationOptions();
    const modelRequest = canViewModelCoverage ? getRegisteredModels() : Promise.resolve({ models: [] });
    const usersRequest = canManageAssets ? getUsers() : Promise.resolve([]);

    try {
      const locationData = await locationRequest;
      setLocations(locationData.locations);
    } catch (err) {
      errors.push(errorMessage(err, "Unable to load locations."));
    }

    const [modelResult, userResult] = await Promise.allSettled([modelRequest, usersRequest]);
    if (modelResult.status === "fulfilled") {
      setModels(modelResult.value.models);
    } else {
      errors.push(errorMessage(modelResult.reason, "Unable to load model coverage."));
    }
    if (userResult.status === "fulfilled") {
      setUsers(userResult.value);
    } else {
      errors.push(errorMessage(userResult.reason, "Unable to load operator assignments."));
    }

    if (errors.length > 0) {
      setError(errors.join(" "));
    }

    setLoading(false);
  }, [canManageAssets, canViewModelCoverage]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void refresh();
    }, 0);

    return () => window.clearTimeout(timeout);
  }, [refresh]);

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
        const data = await getLocationOptions({ q: query }, controller.signal);
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
    if (activeModal) {
      setAssetFormError(null);
    } else {
      setError(null);
    }
    setMessage(null);
    try {
      const nextMessage = await fn();
      setMessage(nextMessage);
      await refresh();
      setActiveModal(null);
    } catch (err) {
      const nextError = err instanceof Error ? err.message : "Request failed.";
      if (activeModal) {
        setAssetFormError(nextError);
      } else {
        setError(nextError);
      }
    } finally {
      setSubmitting(null);
    }
  }

  function openAssetModal(modal: Exclude<AssetModal, null>) {
    setAssetFormError(null);
    setActiveModal(modal);
  }

  function closeAssetModal() {
    if (submitting === "building") return;
    setActiveModal(null);
    setAssetFormError(null);
  }

  function resetBuildingForm() {
    setBuildingId("");
    setBuildingName("");
    setBuildingSiteId("");
    setBuildingMetadata("");
  }

  function validateRequired(value: string, label: string) {
    if (!value.trim()) throw new Error(`${label} is required.`);
    return value.trim();
  }

  function selectLocation(location: LocationOption) {
    if (isSiteLocation(location)) {
      setSelectedLocationId(null);
      setActiveSiteId(location.id);
      setBuildingQuery("");
      setBuildingPage(1);
      return;
    }

    setSelectedLocationId(location.id);
    setActiveSiteId(location.parent_id ?? null);
  }

  function showSiteList() {
    setActiveSiteId(null);
    setSelectedLocationId(null);
    setBuildingQuery("");
    setBuildingPage(1);
  }

  async function handleCreateBuilding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await run("building", async () => {
      const id = validateRequired(buildingId, "Building ID");
      const site_id = validateRequired(buildingSiteId, "Site");
      const name = validateRequired(buildingName, "Name");
      await createBuilding({ id, site_id, name, metadata: parseMetadata(buildingMetadata) });
      resetBuildingForm();
      return `Building ${id} created.`;
    });
  }

  const modelsForLocation = useCallback((location: LocationOption) => {
    const childIds = locations.filter((item) => item.parent_id === location.id).map((item) => item.id);
    return models.filter((model) => modelAppliesGlobally(model) || modelMatches(model, [location.id, location.name, location.parent_id ?? "", ...childIds]));
  }, [locations, models]);

  const modelCoveredLocationCount = useMemo(
    () => locations.filter((location) => modelsForLocation(location).some((model) => model.production_version)).length,
    [locations, modelsForLocation],
  );
  const assignedOperatorsForLocation = useCallback((location: LocationOption | null): AssignedOperator[] => {
    if (!location) return [];

    const childIds = new Set(locations.filter((item) => item.parent_id === location.id).map((item) => item.id));
    const parentSiteId = isSiteLocation(location) ? location.id : location.parent_id;

    return users
      .filter((user) => user.role === "Operator")
      .map((user) => {
        const assignedIds = new Set(user.assigned_site_ids);
        if (assignedIds.has(location.id)) {
          return { user, assignment: "direct" as const };
        }
        if (isSiteLocation(location) && [...childIds].some((childId) => assignedIds.has(childId))) {
          return { user, assignment: "direct" as const };
        }
        if (parentSiteId && assignedIds.has(parentSiteId)) {
          return { user, assignment: "site" as const };
        }
        return null;
      })
      .filter((item): item is AssignedOperator => item != null)
      .sort((a, b) => {
        const statusCompare = a.user.status.localeCompare(b.user.status);
        if (statusCompare !== 0) return statusCompare;
        return a.user.full_name.localeCompare(b.user.full_name);
      });
  }, [locations, users]);
  const selectedOperators = canManageAssets ? assignedOperatorsForLocation(selectedLocation) : [];
  const selectedModels = canViewModelCoverage && selectedLocation ? modelsForLocation(selectedLocation) : [];
  const selectedAnomalyModel = selectedModels.find((m) => modelTask(m) === "anomaly_detection") ?? null;
  const selectedForecastModel = selectedModels.find((m) => modelTask(m) === "forecasting") ?? null;


  return (
    <main className="page assets-page">
      {canManageAssets && (
        <div className="page-head-actions asset-primary-actions">
          <button className="btn btn-primary" type="button" onClick={() => openAssetModal("building")}>
            <Icon name="building" />
            <span>Create Building</span>
          </button>
        </div>
      )}

      {error && <div className="anomaly-error">{error}</div>}
      {message && <div className="models-success">{message}</div>}

      <div className="asset-kpi-strip">
        <div className="asset-stat-card is-primary">
          <span>Total</span>
          <b>{locations.length}</b>
          <small>Locations in index</small>
        </div>
        <div className="asset-stat-card">
          <span>Mapped</span>
          <b>{mappedLocations.length}</b>
          <small>With coordinates</small>
        </div>
        {canViewModelCoverage && (
          <div className="asset-stat-card">
            <span>Model-covered</span>
            <b>{modelCoveredLocationCount}</b>
            <small>Production model match</small>
          </div>
        )}
      </div>

      <div className="assets-workspace">
        <Card
          title="Locations"
          icon="grid"
        >
          {activeSite ? (
            <div className="asset-browser-view is-building-view">
              <div className="asset-toolbar asset-browser-toolbar">
                <div className="asset-toolbar-controls">
                  <button className="asset-browser-back" type="button" onClick={showSiteList}>
                    <Icon name="chevLeft" />
                    <span>Sites</span>
                  </button>
                  <div className="asset-search">
                    <Icon name="search" />
                    <input
                      value={buildingQuery}
                      onChange={(event) => {
                        setBuildingQuery(event.target.value);
                        setBuildingPage(1);
                      }}
                      placeholder="Search buildings"
                    />
                  </div>
                </div>
              </div>

              <div className="asset-browser-list">
                {pagedBuildings.map((location) => (
                  <button
                    key={location.id}
                    type="button"
                    className={[
                      "asset-browser-row",
                      selectedLocationId === location.id && "is-selected",
                    ].filter(Boolean).join(" ")}
                    onClick={() => selectLocation(location)}
                  >
                    <span className="asset-browser-icon">
                      <Icon name="building" />
                    </span>
                    <span className="asset-browser-info">
                      <b title={location.name || location.id}>{displayLocationName(location.name, location.id)}</b>
                      <small title={location.id}>{location.id}</small>
                    </span>
                    <span className="asset-browser-meta">
                      {mappedLocationById.has(location.id) && (
                        <span className="asset-coord-dot" title="Has coordinates" />
                      )}
                    </span>
                  </button>
                ))}
                {activeSiteBuildings.length === 0 && (
                  <div className="asset-empty">No buildings registered for this site.</div>
                )}
                {activeSiteBuildings.length > 0 && filteredActiveSiteBuildings.length === 0 && (
                  <div className="asset-empty">No buildings match the search.</div>
                )}
              </div>

              {filteredActiveSiteBuildings.length > 0 && (
                <div className="pager">
                  <span>
                    Showing {buildingRangeStart}-{buildingRangeEnd} of {filteredActiveSiteBuildings.length} buildings
                  </span>
                  <div className="pager-btns">
                    <button className="pg" type="button" disabled={safeBuildingPage === 1} onClick={() => setBuildingPage((current) => Math.max(1, current - 1))}>
                      <Icon name="chevLeft" style={{ width: 13, height: 13 }} />
                    </button>
                    {Array.from({ length: totalBuildingPages }, (_, index) => index + 1)
                      .filter((page) => page === 1 || page === totalBuildingPages || Math.abs(page - safeBuildingPage) <= 1)
                      .map((page, index, pages) => (
                        <span key={page}>
                          {index > 0 && page - pages[index - 1] > 1 && <span className="muted" style={{ padding: "0 4px" }}>...</span>}
                          <button className={`pg ${safeBuildingPage === page ? "on" : ""}`} type="button" onClick={() => setBuildingPage(page)}>
                            {page}
                          </button>
                        </span>
                      ))}
                    <button className="pg" type="button" disabled={safeBuildingPage === totalBuildingPages} onClick={() => setBuildingPage((current) => Math.min(totalBuildingPages, current + 1))}>
                      <Icon name="chevRight" style={{ width: 13, height: 13 }} />
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="asset-browser-view is-site-view">
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
                      placeholder="Search location or type"
                    />
                  </div>
                </div>
              </div>

              <div className="asset-browser-list">
                {pagedSites.map((location) => {
                  const childCount = buildingsBySiteId.get(location.id)?.length ?? 0;

                  return (
                    <button
                      key={location.id}
                      type="button"
                      className={[
                        "asset-browser-row",
                        selectedLocationId === location.id && "is-selected",
                      ].filter(Boolean).join(" ")}
                      onClick={() => selectLocation(location)}
                    >
                      <span className="asset-browser-icon">
                        <Icon name="map" />
                      </span>
                      <span className="asset-browser-info">
                        <b title={location.name || location.id}>{displayLocationName(location.name, location.id)}</b>
                        <small title={location.id}>{location.id}</small>
                      </span>
                      <span className="asset-browser-meta">
                        <span className="asset-browser-count">{childCount}</span>
                        <Icon name="chevRight" />
                        {mappedLocationById.has(location.id) && (
                          <span className="asset-coord-dot" title="Has coordinates" />
                        )}
                      </span>
                    </button>
                  );
                })}
                {filteredSites.length === 0 && (
                  <div className="asset-empty">No locations match the search.</div>
                )}
              </div>

              {filteredSites.length > 0 && (
                <div className="pager">
                  <span>
                    Showing {locationRangeStart}-{locationRangeEnd} of {filteredSites.length} sites
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
            </div>
          )}
        </Card>

        <Card
          title={selectedLocation ? displayLocationName(selectedLocation.name, selectedLocation.id) : "Asset Details"}
          icon="building"
          actions={selectedLocation && !isSiteLocation(selectedLocation) && selectedPoint ? (
            <a className="btn btn-secondary btn-small" href={osmLocationUrl(selectedPoint)} target="_blank" rel="noreferrer">
              <Icon name="external" />
              <span>Open in OSM</span>
            </a>
          ) : undefined}
        >
          {selectedLocation ? (
            <>
              <div className="asset-map-frame-wrap">
                {selectedPoint ? (
                  <iframe
                    className="asset-map-frame"
                    title={`${displayLocationName(selectedLocation.name, selectedLocation.id)} map`}
                    src={osmEmbedUrl(selectedPoint, 17)}
                    loading="lazy"
                    referrerPolicy="no-referrer-when-downgrade"
                  />
                ) : (
                  <div className="asset-empty" style={{ height: "100%" }}>
                    No coordinates found in this location metadata.
                  </div>
                )}
              </div>

              <div className="asset-detail-body">
                <div className="asset-detail-facts">
                  <div><span>Site</span><b>{isSiteLocation(selectedLocation) ? selectedLocation.id : selectedLocation.parent_id ?? "No site"}</b></div>
                  <div><span>Primary Usage Space</span><b>{titleCase(selectedLocation.location_type)}</b></div>
                  {canViewModelCoverage && (
                    <>
                      <div>
                        <span>Anomaly Detection</span>
                        <b>{selectedAnomalyModel ? `${selectedAnomalyModel.name}_v${selectedAnomalyModel.production_version?.version ?? ""}` : "No model"}</b>
                      </div>
                      <div>
                        <span>Forecasting</span>
                        <b>{selectedForecastModel ? `${selectedForecastModel.name}_v${selectedForecastModel.production_version?.version ?? ""}` : "No model"}</b>
                      </div>
                    </>
                  )}
                </div>

                {canManageAssets && (
                  <div className="asset-detail-section">
                    <span className="asset-summary-label">Assigned Operators</span>
                    <div className="asset-operator-list">
                      {selectedOperators.map(({ user }) => (
                        <div className="asset-operator-row" key={user.id}>
                          <span className={`user-status-dot ${operatorStatusTone(user.status)}`} aria-label={statusLabel(user.status)} />
                          <span>
                            <b>{user.full_name}</b>
                            <small>{user.email}</small>
                          </span>
                          <button className="btn btn-small" type="button" onClick={() => setEditingOperator(user)}>
                            <span>Edit</span>
                          </button>
                        </div>
                      ))}
                      {selectedOperators.length === 0 && (
                        <span className="asset-operator-empty">No operators assigned.</span>
                      )}
                    </div>
                  </div>
                )}

              </div>
            </>
          ) : (
            <div className="asset-detail-empty-state">
              <Icon name="building" />
              <b>No location selected</b>
              <small>Pick a location from the list to see its details here.</small>
            </div>
          )}
        </Card>
      </div>
      {canManageAssets && activeModal && (
        <Modal
          title="Create Building"
          description="Attach a building to a site."
          className="asset-modal"
          onClose={closeAssetModal}
        >
          {activeModal === "building" && (
            <form className="asset-form" onSubmit={handleCreateBuilding}>
              <Field label="Building ID">
                <input className="input" value={buildingId} onChange={(event) => setBuildingId(event.target.value)} placeholder="Panther_lodging_Cora" required />
              </Field>
              <Field label="Site">
                <select className="input" value={buildingSiteId} onChange={(event) => setBuildingSiteId(event.target.value)} required>
                  <option value="">Select site</option>
                  {siteOptions.map((site) => (
                    <option value={site.id} key={site.id}>{site.id}</option>
                  ))}
                </select>
              </Field>
              <Field label="Name">
                <input className="input" value={buildingName} onChange={(event) => setBuildingName(event.target.value)} required />
              </Field>
              <Field label="Metadata JSON">
                <textarea className="textarea" value={buildingMetadata} onChange={(event) => setBuildingMetadata(event.target.value)} />
              </Field>
              {assetFormError && <FormMessage tone="error">{assetFormError}</FormMessage>}
              <button
                className="btn btn-primary"
                type="submit"
                disabled={submitting === "building"}
              >
                <Icon name={submitting === "building" ? "refresh" : "plus"} className={submitting === "building" ? "spin" : undefined} />
                <span>{submitting === "building" ? "Creating..." : "Create Building"}</span>
              </button>
            </form>
          )}
        </Modal>
      )}

      {editingOperator && (
        <UserEditModal
          user={editingOperator}
          currentEmail={currentUser?.email.toLowerCase() ?? ""}
          currentUserIsGlobalAdmin={Boolean(currentUser?.isGlobalAdmin)}
          locations={locations}
          allowDelete={false}
          lockRole="Operator"
          onClose={() => setEditingOperator(null)}
          onLocationsDiscovered={(newLocations) => {
            setLocations((current) => {
              const existing = new Set(current.map((location) => location.id));
              return [...current, ...newLocations.filter((location) => !existing.has(location.id))];
            });
          }}
          onSaved={(updated) => {
            setUsers((current) => current.map((user) => (user.id === updated.id ? updated : user)));
            setMessage(`${updated.full_name} was updated.`);
          }}
        />
      )}
    </main>
  );
}
