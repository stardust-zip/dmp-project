"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/common/icons";
import { displayLocationName, humanizeIdentifier } from "@/lib/format";
import { getLocationOptions, type LocationOption } from "@/lib/models-api";

interface RecentLocationEntry {
  id: string;
  name: string;
}

export interface UserLocationPickerProps {
  selectedIds: string[];
  selectedLocations: LocationOption[];
  siteById: Map<string, LocationOption>;
  onAdd: (location: LocationOption) => void;
  onRemove: (locationId: string) => void;
  recentLocationEntries?: RecentLocationEntry[];
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
}: UserLocationPickerProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<LocationOption[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    const queryText = query.trim();
    if (queryText.length < 2) {
      setResults([]);
      setSearching(false);
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

  const unassignedResults = results.filter((loc) => !selectedIds.includes(loc.id));

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
                      onAdd({ id: entry.id, name: entry.name } as LocationOption);
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
        {searching ? (
          <div className="user-location-empty">Searching locations...</div>
        ) : (
          unassignedResults.slice(0, 8).map((loc) => (
            <button
              key={loc.id}
              className="user-location-result"
              type="button"
              onClick={() => {
                onAdd(loc);
                setQuery("");
              }}
            >
              <span>
                <b>{displayLocationName(loc.name, loc.id)}</b>
                <small>
                  {locationTypeLabel(loc)}
                  {loc.parent_id
                    ? ` in ${displayLocationName(siteById.get(loc.parent_id)?.name, loc.parent_id)}`
                    : ""}
                </small>
              </span>
              <Icon name="plus" />
            </button>
          ))
        )}
        {!searching && query.trim().length < 2 && (
          <div className="user-location-empty">Type at least 2 characters to search locations.</div>
        )}
        {!searching && query.trim().length >= 2 && !unassignedResults.length && (
          <div className="user-location-empty">No matching unassigned locations.</div>
        )}
      </div>

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
