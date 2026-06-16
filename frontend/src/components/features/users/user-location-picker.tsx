"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/common/icons";
import { displayLocationName, humanizeIdentifier } from "@/lib/format";
import { getLocationOptions, type LocationOption } from "@/lib/models-api";

interface RecentLocationEntry {
  id: string;
  name: string;
  parent_id?: string | null;
  location_type?: string | null;
}

export interface UserLocationPickerProps {
  selectedIds: string[];
  selectedLocations: LocationOption[];
  siteById: Map<string, LocationOption>;
  onAdd: (location: LocationOption) => void;
  onRemove: (locationId: string) => void;
  recentLocationEntries?: RecentLocationEntry[];
  enforceSingleSite?: boolean;
}

function locationTypeLabel(location: LocationOption) {
  return location.location_type ? humanizeIdentifier(location.location_type) : "Location";
}

export function UserLocationPicker({
  selectedIds,
  selectedLocations,
  siteById,
  onAdd,
  onRemove,
  recentLocationEntries = [],
  enforceSingleSite = false,
}: UserLocationPickerProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<LocationOption[]>([]);
  const [searching, setSearching] = useState(false);
  const [scopeIssue, setScopeIssue] = useState<string | null>(null);

  useEffect(() => {
    const queryText = query.trim();
    if (queryText.length < 2) {
      return;
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      setSearching(true);
      try {
        const data = await getLocationOptions(
          { q: queryText, includeArchived: false, limit: 25 },
          controller.signal,
        );
        setResults(data.locations);
      } catch {
        if (!controller.signal.aborted) setResults([]);
      } finally {
        if (!controller.signal.aborted) setSearching(false);
      }
    }, 180);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [query]);

  function rootSiteId(location: LocationOption) {
    return location.location_type === "site" ? location.id : location.parent_id ?? location.id;
  }

  const queryText = query.trim();
  const selectedSiteIds = new Set(selectedLocations.map(rootSiteId).filter(Boolean));
  const selectedSiteId = selectedSiteIds.size === 1 ? [...selectedSiteIds][0] : null;
  const visibleResults = queryText.length >= 2 ? results : [];
  const unassignedResults = visibleResults.filter((loc) => !selectedIds.includes(loc.id));
  const isSearching = queryText.length >= 2 && searching;

  function canAddLocation(location: LocationOption) {
    if (!enforceSingleSite || !selectedSiteId) return true;
    return rootSiteId(location) === selectedSiteId;
  }

  function addLocation(location: LocationOption) {
    if (!canAddLocation(location)) {
      setScopeIssue("Operators can be assigned to multiple buildings, but they must all belong to one site.");
      return;
    }
    setScopeIssue(null);
    onAdd(location);
    setQuery("");
  }

  return (
    <div className="user-location-picker">
      {/* ── Recent locations quick-add ── */}
      {recentLocationEntries.length > 0 && (
        <div className="user-location-recent">
          <span className="user-location-recent-label">Recent</span>
          <div className="user-location-recent-chips">
            {recentLocationEntries
              .filter((entry) => !selectedIds.includes(entry.id))
              .slice(0, 6)
              .map((entry) => (
                <button
                  key={entry.id}
                  className="user-location-chip user-location-chip-recent"
                  type="button"
                  onClick={() => {
                    const existing = selectedLocations.find((loc) => loc.id === entry.id);
                    if (existing) {
                      onRemove(entry.id);
                    } else {
                      addLocation({
                        id: entry.id,
                        name: entry.name,
                        parent_id: entry.parent_id ?? null,
                        location_type: entry.location_type ?? null,
                      } as LocationOption);
                    }
                  }}
                >
                  <span>{displayLocationName(entry.name, entry.id)}</span>
                  <Icon name={selectedIds.includes(entry.id) ? "x" : "plus"} />
                </button>
              ))}
          </div>
        </div>
      )}

      {/* ── Search ── */}
      <div className="user-location-search">
        <Icon name="search" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search building, site, or location ID"
        />
      </div>

      {/* ── Results ── */}
      <div className="user-location-results">
        {isSearching ? (
          <div className="user-location-empty">Searching locations...</div>
        ) : (
          unassignedResults.slice(0, 8).map((loc) => {
            const allowed = canAddLocation(loc);
            return (
              <button
                key={loc.id}
                className={`user-location-result ${allowed ? "" : "is-disabled"}`}
                type="button"
                disabled={!allowed}
                onClick={() => addLocation(loc)}
              >
                <span>
                  <b>{displayLocationName(loc.name, loc.id)}</b>
                  <small>
                    {allowed
                      ? `${locationTypeLabel(loc)}${loc.parent_id ? ` in ${displayLocationName(siteById.get(loc.parent_id)?.name, loc.parent_id)}` : ""}`
                      : "Different site from the current operator assignment"}
                  </small>
                </span>
                <Icon name={allowed ? "plus" : "x"} />
              </button>
            );
          })
        )}
        {!isSearching && queryText.length < 2 && (
          <div className="user-location-empty">Type at least 2 characters to search locations.</div>
        )}
        {!isSearching && queryText.length >= 2 && !unassignedResults.length && (
          <div className="user-location-empty">No matching unassigned locations.</div>
        )}
      </div>
      {scopeIssue && <span className="user-field-help">{scopeIssue}</span>}

      {/* ── Selected chips ── */}
      <div className="user-location-chips">
        {selectedLocations.length > 0 && (
          <span className="user-location-count">
            {selectedLocations.length} location{selectedLocations.length !== 1 ? "s" : ""} selected
          </span>
        )}
        {selectedLocations.map((loc) => (
          <button
            key={loc.id}
            className="user-location-chip"
            type="button"
            onClick={() => onRemove(loc.id)}
            title="Remove location"
          >
            <span>{displayLocationName(loc.name, loc.id)}</span>
            <Icon name="x" />
          </button>
        ))}
        {!selectedLocations.length && (
          <span className="user-location-placeholder">Assign one or more locations.</span>
        )}
      </div>
    </div>
  );
}
