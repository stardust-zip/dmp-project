"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { Icon } from "@/components/common/icons";
import { Card, Field, FormMessage, Modal } from "@/components/common/primitives";
import { displayLocationName, displayModelName, humanizeIdentifier, isSiteLocation, locationSearchText } from "@/lib/format";
import {
  createBuilding,
  createSite,
  getLocationOptions,
  getRegisteredModels,
  updateLocation,
  type LocationOption,
  type RegisteredModel,
} from "@/lib/models-api";

type LocationFilter = "all" | "active" | "archived";
type AssetModal = "site" | "building" | null;
type DetailTarget = { kind: "location"; item: LocationOption } | null;

const LOCATION_INDEX_LIMIT = 1000;
const LOCATIONS_PER_PAGE = 24;

type GeoPoint = {
  lat: number;
  lon: number;
};

type MappedLocation = {
  location: LocationOption;
  point: GeoPoint;
};

type MapSearchResult = {
  location: LocationOption;
  point: GeoPoint | null;
};

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

function formatCoordinate(value: number) {
  return value.toFixed(5);
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
  const { session } = useAuth();
  const currentUser = session?.user;
  const canManageAssets = currentUser?.role === "Admin";
  const canViewModelCoverage = currentUser?.role === "Admin" || currentUser?.role === "AI_Engineer";
  const mapSearchRef = useRef<HTMLDivElement | null>(null);
  const mapStatsRef = useRef<HTMLDivElement | null>(null);
  const [locations, setLocations] = useState<LocationOption[]>([]);

  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [activeModal, setActiveModal] = useState<AssetModal>(null);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [mapStatsOpen, setMapStatsOpen] = useState(false);
  const [assetFormError, setAssetFormError] = useState<string | null>(null);
  const [detailTarget, setDetailTarget] = useState<DetailTarget>(null);

  const [siteId, setSiteId] = useState("");
  const [siteName, setSiteName] = useState("");
  const [siteMetadata, setSiteMetadata] = useState("");

  const [buildingId, setBuildingId] = useState("");
  const [buildingName, setBuildingName] = useState("");
  const [buildingSiteId, setBuildingSiteId] = useState("");
  const [buildingMetadata, setBuildingMetadata] = useState("");

  const [locationQuery, setLocationQuery] = useState("");
  const [mapQuery, setMapQuery] = useState("");
  const [mapDropdownOpen, setMapDropdownOpen] = useState(false);
  const [selectedMapLocationId, setSelectedMapLocationId] = useState<string | null>(null);
  const [searchedLocations, setSearchedLocations] = useState<LocationOption[] | null>(null);
  const [mapSearchedLocations, setMapSearchedLocations] = useState<LocationOption[] | null>(null);
  const [locationSearchLoading, setLocationSearchLoading] = useState(false);
  const [mapSearchLoading, setMapSearchLoading] = useState(false);

  const [locationStatusFilter, setLocationStatusFilter] = useState<LocationFilter>("all");
  const [locationPage, setLocationPage] = useState(1);

  const siteOptions = useMemo(() => locations.filter((location) => isSiteLocation(location) && !location.archived), [locations]);
  const locationById = useMemo(() => new Map(locations.map((location) => [location.id, location])), [locations]);

  const activeLocationCount = useMemo(() => locations.filter((location) => !location.archived).length, [locations]);
  const archivedLocationCount = locations.length - activeLocationCount;
  const locationSource = locationQuery.trim() && searchedLocations ? searchedLocations : locations;
  const mappedLocations = useMemo<MappedLocation[]>(
    () => locations.map((location) => ({ location, point: locationPoint(location) })).filter((item): item is MappedLocation => item.point != null),
    [locations],
  );
  const mappedLocationById = useMemo(() => new Map(mappedLocations.map((item) => [item.location.id, item])), [mappedLocations]);
  const mapCenter = useMemo<GeoPoint | null>(() => {
    if (mappedLocations.length === 0) return null;
    return {
      lat: mappedLocations.reduce((sum, item) => sum + item.point.lat, 0) / mappedLocations.length,
      lon: mappedLocations.reduce((sum, item) => sum + item.point.lon, 0) / mappedLocations.length,
    };
  }, [mappedLocations]);

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
  const mapLocationById = useMemo(() => {
    const indexed = new Map(locations.map((location) => [location.id, location]));
    (mapSearchedLocations ?? []).forEach((location) => indexed.set(location.id, location));
    (searchedLocations ?? []).forEach((location) => indexed.set(location.id, location));
    return indexed;
  }, [locations, mapSearchedLocations, searchedLocations]);
  const mapSearchResults = useMemo<MapSearchResult[]>(() => {
    const query = mapQuery.trim().toLowerCase();
    const source = query && mapSearchedLocations ? mapSearchedLocations : locations;
    const filtered = query && !mapSearchedLocations
      ? source.filter((location) =>
          `${locationSearchText(location, location.parent_id ? locationById.get(location.parent_id) : undefined)} ${location.archived ? "archived" : "active"}`.includes(query),
        )
      : source;

    return filtered.map((location) => ({ location, point: locationPoint(location) })).slice(0, 10);
  }, [locationById, locations, mapQuery, mapSearchedLocations]);
  const activeMapLocationId = useMemo(() => {
    const selectedStillVisible = selectedMapLocationId
      ? mapLocationById.has(selectedMapLocationId) || mapSearchResults.some((item) => item.location.id === selectedMapLocationId)
      : false;
    if (selectedStillVisible) return selectedMapLocationId;
    return mapSearchResults.find((item) => item.point)?.location.id ?? mappedLocations[0]?.location.id ?? null;
  }, [mapLocationById, mapSearchResults, mappedLocations, selectedMapLocationId]);
  const selectedMapLocation = activeMapLocationId ? mapLocationById.get(activeMapLocationId) ?? null : null;
  const selectedMapPoint = selectedMapLocation ? locationPoint(selectedMapLocation) : null;
  const locationRangeStart = filteredLocations.length ? (safeLocationPage - 1) * LOCATIONS_PER_PAGE + 1 : 0;
  const locationRangeEnd = Math.min(safeLocationPage * LOCATIONS_PER_PAGE, filteredLocations.length);
  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const locationRequest = getLocationOptions({ includeArchived: true, limit: LOCATION_INDEX_LIMIT });
      const modelRequest = canViewModelCoverage ? getRegisteredModels() : Promise.resolve({ models: [] });
      const [locationData, modelData] = await Promise.all([locationRequest, modelRequest]);
      setLocations(locationData.locations);
      setModels(modelData.models);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load asset data.");
    } finally {
      setLoading(false);
    }
  }, [canViewModelCoverage]);

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

  useEffect(() => {
    const query = mapQuery.trim();
    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      if (!query) {
        setMapSearchedLocations(null);
        setMapSearchLoading(false);
        return;
      }

      setMapSearchLoading(true);
      try {
        const data = await getLocationOptions({ q: query, includeArchived: true, limit: LOCATION_INDEX_LIMIT }, controller.signal);
        setMapSearchedLocations(data.locations);
      } catch {
        if (!controller.signal.aborted) setMapSearchedLocations([]);
      } finally {
        if (!controller.signal.aborted) setMapSearchLoading(false);
      }
    }, query ? 180 : 0);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [mapQuery]);

  useEffect(() => {
    if (!mapDropdownOpen) return;

    const closeIfOutside = (event: PointerEvent) => {
      if (!mapSearchRef.current?.contains(event.target as Node)) {
        setMapDropdownOpen(false);
      }
    };

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMapDropdownOpen(false);
      }
    };

    document.addEventListener("pointerdown", closeIfOutside);
    document.addEventListener("keydown", closeOnEscape);

    return () => {
      document.removeEventListener("pointerdown", closeIfOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [mapDropdownOpen]);

  useEffect(() => {
    if (!mapStatsOpen) return;

    const closeIfOutside = (event: PointerEvent) => {
      if (!mapStatsRef.current?.contains(event.target as Node)) {
        setMapStatsOpen(false);
      }
    };

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMapStatsOpen(false);
      }
    };

    document.addEventListener("pointerdown", closeIfOutside);
    document.addEventListener("keydown", closeOnEscape);

    return () => {
      document.removeEventListener("pointerdown", closeIfOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [mapStatsOpen]);

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
    if (submitting === "site" || submitting === "building") return;
    setActiveModal(null);
    setAssetFormError(null);
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

  function validateRequired(value: string, label: string) {
    if (!value.trim()) throw new Error(`${label} is required.`);
    return value.trim();
  }

  async function handleCreateSite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await run("site", async () => {
      const id = validateRequired(siteId, "Site ID");
      const name = validateRequired(siteName, "Name");
      await createSite({ id, name, metadata: parseMetadata(siteMetadata) });
      resetSiteForm();
      return `Site ${id} created.`;
    });
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

  async function toggleLocationArchive(location: LocationOption) {
    const nextArchived = !location.archived;
    const action = `archive-${location.id}`;
    setSubmitting(action);
    setError(null);
    setMessage(null);
    try {
      const updated = await updateLocation(location.id, { archived: nextArchived });
      setLocations((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setSearchedLocations((current) => current?.map((item) => (item.id === updated.id ? updated : item)) ?? null);
      setMapSearchedLocations((current) => current?.map((item) => (item.id === updated.id ? updated : item)) ?? null);
      setDetailTarget((current) => current?.kind === "location" && current.item.id === updated.id ? { kind: "location", item: updated } : current);
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
  const selectedMapModels = selectedMapLocation ? modelsForLocation(selectedMapLocation) : [];
  const selectedMapChildren = selectedMapLocation ? locations.filter((item) => item.parent_id === selectedMapLocation.id) : [];

  const selectedLocation = detailTarget?.kind === "location" ? detailTarget.item : null;
  const selectedPoint = selectedLocation ? locationPoint(selectedLocation) : null;

  return (
    <main className="page assets-page">
      <div className="page-head assets-head">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-sub">
            {canManageAssets
              ? "Asset dashboard for site hierarchy, building inventory, metadata, and model coverage."
              : "Asset dashboard for your accessible site hierarchy, building inventory, and metadata."}
          </p>
        </div>
        {canManageAssets && (
          <div className="page-head-actions asset-primary-actions">
            <button className="btn btn-primary" type="button" onClick={() => openAssetModal("site")}>
              <Icon name="map" />
              <span>Create Site</span>
            </button>
            <button className="btn btn-primary" type="button" onClick={() => openAssetModal("building")}>
              <Icon name="building" />
              <span>Create Building</span>
            </button>
          </div>
        )}
      </div>

      {error && <div className="anomaly-error">{error}</div>}
      {message && <div className="models-success">{message}</div>}

      <div className="assets-layout">
        <Card
          title="Asset Map"
          sub={mappedLocations.length ? `${mappedLocations.length} locations geocoded from metadata` : "Add latitude and longitude metadata to enable the map"}
          icon="map"
          actions={(
            <div className="asset-map-actions">
              <button className="btn btn-secondary btn-small" type="button" onClick={() => setGalleryOpen(true)}>
                <Icon name="grid" />
                <span>Location Gallery</span>
              </button>
              <div className="asset-map-stats-wrap" ref={mapStatsRef}>
                <button className="btn btn-secondary btn-small" type="button" aria-expanded={mapStatsOpen} onClick={() => setMapStatsOpen((open) => !open)}>
                  <Icon name="info" />
                  <span>Stats</span>
                </button>
                {mapStatsOpen && (
                  <div className="asset-map-stats-popover" role="dialog" aria-label="Asset map stats">
                    <div className="asset-map-stats-head">
                      <b>Asset Stats</b>
                      <small>{loading ? "Loading asset index..." : `${locations.length} locations loaded`}</small>
                    </div>
                    <div className="asset-map-stats-grid">
                      <div className="asset-stat-card is-primary">
                        <span>Total</span>
                        <b>{locations.length}</b>
                        <small>Locations in index</small>
                      </div>
                      <div className="asset-stat-card">
                        <span>Active</span>
                        <b>{activeLocationCount}</b>
                        <small>Available in workflows</small>
                      </div>
                      <div className="asset-stat-card">
                        <span>Archived</span>
                        <b>{archivedLocationCount}</b>
                        <small>Hidden by default</small>
                      </div>
                      <div className="asset-stat-card">
                        <span>Mapped</span>
                        <b>{mappedLocations.length}</b>
                        <small>With coordinates</small>
                      </div>
                      <div className="asset-stat-card">
                        <span>Coverage</span>
                        <b>{Math.round((mappedLocations.length / Math.max(locations.length, 1)) * 100)}%</b>
                        <small>{locations.length - mappedLocations.length} missing coords</small>
                      </div>
                      {canViewModelCoverage && (
                        <div className="asset-stat-card">
                          <span>Model-covered</span>
                          <b>{modelCoveredLocationCount}</b>
                          <small>Production model match</small>
                        </div>
                      )}
                    </div>
                    <div className="asset-map-stats-foot">
                      <span>Map center</span>
                      <b>{mapCenter ? `${formatCoordinate(mapCenter.lat)}, ${formatCoordinate(mapCenter.lon)}` : "No map center"}</b>
                    </div>
                  </div>
                )}
              </div>
              {(selectedMapPoint ?? mapCenter) && (
                <a className="btn btn-secondary btn-small" href={osmLocationUrl(selectedMapPoint ?? mapCenter!, selectedMapPoint ? 18 : 3)} target="_blank" rel="noreferrer">
                  <Icon name="external" />
                  <span>Open OSM</span>
                </a>
              )}
            </div>
          )}
        >
          <div className="asset-map-workspace">
            <div className="asset-map-command">
              <div className="asset-map-search-wrap" ref={mapSearchRef}>
                <div className="asset-search asset-map-search">
                  <Icon name="search" />
                  <input
                    value={mapQuery}
                    onChange={(event) => {
                      setMapQuery(event.target.value);
                      setMapDropdownOpen(true);
                    }}
                    onFocus={() => {
                      if (mapQuery.trim() || mapSearchResults.length > 0) setMapDropdownOpen(true);
                    }}
                    placeholder="Search DB locations, e.g. Panther"
                  />
                </div>
                {mapDropdownOpen && (mapQuery.trim() || mapSearchLoading) && (
                  <div className="asset-map-dropdown">
                    {mapSearchLoading && <div className="asset-map-no-results">Searching database...</div>}
                    {!mapSearchLoading && mapSearchResults.map(({ location, point }) => (
                      <button
                        className={activeMapLocationId === location.id ? "is-selected" : ""}
                        type="button"
                        key={location.id}
                        onClick={() => {
                          setSelectedMapLocationId(location.id);
                          setMapDropdownOpen(false);
                        }}
                      >
                        <Icon name={isSiteLocation(location) ? "map" : "building"} />
                        <span>
                          <b>{displayLocationName(location.name, location.id)}</b>
                          <small>{location.id}</small>
                        </span>
                        <em>{point ? `${formatCoordinate(point.lat)}, ${formatCoordinate(point.lon)}` : "No coords"}</em>
                      </button>
                    ))}
                    {!mapSearchLoading && mapQuery.trim() && mapSearchResults.length === 0 && <div className="asset-map-no-results">No database location matches this search.</div>}
                  </div>
                )}
              </div>
            </div>

            <div className="asset-map-content">
              <div className="asset-map-main">
                {(selectedMapPoint ?? mapCenter) ? (
                  <iframe
                    className="asset-map-frame"
                    title={selectedMapLocation ? `${displayLocationName(selectedMapLocation.name, selectedMapLocation.id)} map` : "Asset map"}
                    src={osmEmbedUrl(selectedMapPoint ?? mapCenter!, selectedMapPoint ? 17 : 3)}
                    loading="lazy"
                    referrerPolicy="no-referrer-when-downgrade"
                  />
                ) : (
                  <div className="asset-empty">No latitude and longitude metadata found yet.</div>
                )}
              </div>

              <aside className="asset-map-detail-panel" aria-label="Selected location details">
                {selectedMapLocation ? (
                  <>
                    <div className="asset-map-detail-head">
                      <span className="asset-summary-label">Selected location</span>
                      <h3>{displayLocationName(selectedMapLocation.name, selectedMapLocation.id)}</h3>
                      <p>{selectedMapLocation.id}</p>
                    </div>
                    <div className="asset-map-detail-facts">
                      <div><span>Type</span><b>{titleCase(selectedMapLocation.location_type)}</b></div>
                      <div><span>Site</span><b>{isSiteLocation(selectedMapLocation) ? selectedMapLocation.id : selectedMapLocation.parent_id ?? "No site assigned"}</b></div>
                      <div><span>Status</span><b>{selectedMapLocation.archived ? "Archived" : "Active"}</b></div>
                      <div><span>Coordinates</span><b>{selectedMapPoint ? `${formatCoordinate(selectedMapPoint.lat)}, ${formatCoordinate(selectedMapPoint.lon)}` : "No coordinates"}</b></div>
                      {canViewModelCoverage && <div><span>Models</span><b>{selectedMapModels.length}</b></div>}
                      <div><span>Child assets</span><b>{selectedMapChildren.length}</b></div>
                    </div>
                    {selectedMapPoint && (
                      <a className="btn btn-secondary btn-small asset-map-osm-action" href={osmLocationUrl(selectedMapPoint)} target="_blank" rel="noreferrer">
                        <Icon name="external" />
                        <span>Open in OSM</span>
                      </a>
                    )}
                    {canManageAssets && (
                      <button
                        className="btn btn-primary btn-small asset-map-archive-action"
                        type="button"
                        disabled={submitting === `archive-${selectedMapLocation.id}`}
                        onClick={() => void toggleLocationArchive(selectedMapLocation)}
                      >
                        <Icon name="flag" />
                        <span>{selectedMapLocation.archived ? "Restore Location" : "Archive Location"}</span>
                      </button>
                    )}
                    <div className="asset-map-detail-section">
                      <span className="asset-summary-label">Related assets</span>
                      <div className="asset-detail-list compact">
                        {selectedMapChildren.slice(0, 4).map((item) => <span key={item.id} title={item.id}>{displayLocationName(item.name, item.id)}</span>)}
                        {selectedMapChildren.length === 0 && <span>No direct child locations</span>}
                      </div>
                    </div>
                    {canViewModelCoverage && (
                      <div className="asset-map-detail-section">
                        <span className="asset-summary-label">Model usage</span>
                        <div className="asset-detail-list compact">
                          {selectedMapModels.map((model) => <span key={model.name} title={model.name}>{displayModelName(model.name)}</span>)}
                          {selectedMapModels.length === 0 && <span>No matching model tags or names found</span>}
                        </div>
                      </div>
                    )}
                    <div className="asset-map-detail-section">
                      <span className="asset-summary-label">Metadata JSON</span>
                      <pre className="asset-json in-panel">{shortJson(selectedMapLocation.metadata)}</pre>
                    </div>
                  </>
                ) : (
                  <div className="asset-map-detail-empty">
                    <span className="asset-summary-label">Selected location</span>
                    <b>No mapped asset selected</b>
                    <small>Search or pick a mapped location from the gallery.</small>
                  </div>
                )}
              </aside>
            </div>
          </div>
        </Card>
      </div>

      {galleryOpen && (
        <Modal
          title="Location Gallery"
          description={loading ? "Loading locations and model coverage" : `${filteredLocations.length} of ${locations.length} locations found`}
          className="asset-gallery-modal"
          onClose={() => setGalleryOpen(false)}
        >
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
              <button
                className="asset-tile"
                type="button"
                key={location.id}
                onClick={() => {
                  setGalleryOpen(false);
                  setSelectedMapLocationId(location.id);
                  setMapQuery("");
                  setMapSearchedLocations(null);
                  setMapDropdownOpen(false);
                }}
              >
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
                  {canViewModelCoverage && <span>{modelsForLocation(location).length} models</span>}
                  <span>{mappedLocationById.has(location.id) ? "Mapped" : "No coords"}</span>
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
        </Modal>
      )}

      {canManageAssets && activeModal && (
        <Modal
          title={activeModal === "site" ? "Create Site" : "Create Building"}
          description={activeModal === "site" ? "Add a top-level location." : "Attach a building to a site."}
          className="asset-modal"
          onClose={closeAssetModal}
        >
              {activeModal === "site" && (
                <form className="asset-form" onSubmit={handleCreateSite}>
                  <Field label="Site ID">
                    <input className="input" value={siteId} onChange={(event) => setSiteId(event.target.value)} placeholder="Panther" required />
                  </Field>
                  <Field label="Name">
                    <input className="input" value={siteName} onChange={(event) => setSiteName(event.target.value)} placeholder="Panther" required />
                  </Field>
                  <Field label="Metadata JSON">
                    <textarea className="textarea" value={siteMetadata} onChange={(event) => setSiteMetadata(event.target.value)} placeholder='{"timezone":"UTC"}' />
                  </Field>
                  {assetFormError && <FormMessage tone="error">{assetFormError}</FormMessage>}
                  <button
                    className="btn btn-primary"
                    type="submit"
                    disabled={submitting === "site"}
                  >
                    <Icon name={submitting === "site" ? "refresh" : "plus"} className={submitting === "site" ? "spin" : undefined} />
                    <span>{submitting === "site" ? "Creating..." : "Create Site"}</span>
                  </button>
                </form>
              )}
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
                    <dt>Coordinates</dt><dd>{selectedPoint ? `${formatCoordinate(selectedPoint.lat)}, ${formatCoordinate(selectedPoint.lon)}` : "No coordinates in metadata"}</dd>
                  </dl>
                  {selectedPoint && (
                    <>
                      <div className="sec-label">OpenStreetMap</div>
                      <div className="asset-osm-preview">
                        <iframe
                          title={`${displayLocationName(selectedLocation.name, selectedLocation.id)} map`}
                          src={osmEmbedUrl(selectedPoint)}
                          loading="lazy"
                          referrerPolicy="no-referrer-when-downgrade"
                        />
                      </div>
                      <a className="btn btn-secondary asset-osm-link" href={osmLocationUrl(selectedPoint)} target="_blank" rel="noreferrer">
                        <Icon name="external" />
                        <span>Open in OpenStreetMap</span>
                      </a>
                    </>
                  )}
                  <pre className="asset-json">{shortJson(selectedLocation.metadata)}</pre>
                  <div className="sec-label">Related Assets</div>
                  <div className="asset-detail-list">
                    {locations.filter((item) => item.parent_id === selectedLocation.id).map((item) => <span key={item.id} title={item.id}>{displayLocationName(item.name, item.id)}</span>)}
                    {locations.filter((item) => item.parent_id === selectedLocation.id).length === 0 && <span>No direct child locations</span>}
                  </div>
                  {canViewModelCoverage && (
                    <>
                      <div className="sec-label">Model Usage</div>
                      <div className="asset-detail-list">
                        {modelsForLocation(selectedLocation).map((model) => <span key={model.name} title={model.name}>{displayModelName(model.name)}</span>)}
                        {modelsForLocation(selectedLocation).length === 0 && <span>No matching model tags or names found</span>}
                      </div>
                    </>
                  )}
                </>
              )}
            </div>
            <div className="drawer-foot">
              {canManageAssets && selectedLocation && (
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
