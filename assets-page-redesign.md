# Assets Page Redesign Plan

**File:** `frontend/src/components/features/assets/assets-page.tsx`  
**CSS:** `frontend/src/styles/globals.css` (assets section, ~lines 2944–4096)  
**Branch:** create off `minh/ui-ux`

---

## 1. Problem Statement

The current assets page has five structural problems that require a redesign:

| Problem | Root Cause |
|---|---|
| Location list is buried in a modal | Gallery was added as an afterthought to the map card |
| Stats are hidden in a popover | No persistent summary area was designed |
| Map is the full-page hero but has no interactivity | iframe can't respond to clicks; frame is too prominent |
| Two parallel detail experiences | Map side panel + drawer both exist; drawer is dead code |
| 22 state variables for what is essentially a browse+select page | Accumulated from adding features without refactoring |

**Goal:** Rebuild with a mental model of **list-first, map-as-support** — users browse locations in an inline list; selecting one updates the map and detail panel beside it.

---

## 2. Target Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ Asset Management                  [Create Site] [Create Building] │
│ Site hierarchy, building inventory and model coverage.           │
├────────┬──────────┬──────────┬──────────┬────────────────────────┤
│ Total  │  Active  │ Archived │  Mapped  │    Model-covered       │
│  124   │    98    │    26    │    87    │         45             │
│ assets │  in use  │  hidden  │geocoded  │   prod model           │
└────────┴──────────┴──────────┴──────────┴────────────────────────┘

┌──────────────────────────┬───────────────────────────────────────┐
│ LOCATIONS                │                                       │
│ [🔍 Search...] [All][Active][Archived]  ┌─────────────────────┐ │
│                          │  OSM iframe  │                     │ │
│ ● Panther         Site   │  (zoom 17 if│  selected, else     │ │
│   panther_bldg_A  Bldg ↳ │   centroid  │  zoom 3)            │ │
│   panther_bldg_B  Bldg ↳ │             └─────────────────────┘ │
│ ● Summit          Site   │                                       │
│   summit_main     Bldg ↳ │  ── PANTHER ────────────────────────  │
│   summit_annex    Bldg ↳ │  panther · Site · Active             │
│ ● Kilo            Site   │  ┌──────┬──────┬──────┬───────────┐  │
│   ...                    │  │ Type │ Site │Coords│  Models   │  │
│                          │  └──────┴──────┴──────┴───────────┘  │
│ 1–24 of 98  < 1 2 3 …5 > │  [Anomaly] [Open OSM] [Archive]     │
│                          │                                       │
│                          │  ── Operators ──                      │
│                          │  ● John Doe · Available   [Edit]     │
│                          │  ● Jane Smith · Busy      [Edit]     │
│                          │                                       │
│                          │  ── Models ──                         │
│                          │  anomaly_v2   prediction_v1           │
│                          │                                       │
│                          │  ── Metadata ──                       │
│                          │  { "timezone": "UTC", ... }           │
└──────────────────────────┴───────────────────────────────────────┘
```

**Responsive breakpoints** (mirrors existing pattern):
- `≥ 960px`: two-column split (left list 38%, right map+detail 62%)
- `< 960px`: stacked — KPI strip → map → detail → list
- `< 640px`: KPI strip wraps to 2 columns; list full-width

---

## 3. State Audit

### Variables to remove

| Variable | Why removed |
|---|---|
| `galleryOpen` | Gallery modal is replaced by inline list |
| `mapStatsOpen` | Stats popover replaced by KPI strip |
| `mapQuery` | Single `locationQuery` drives both list + map |
| `mapDropdownOpen` | No dropdown; list IS the search results |
| `mapSearchedLocations` | Merged into single search path |
| `mapSearchLoading` | Merged into `locationSearchLoading` |
| `detailTarget` | Replaced by `selectedLocationId` |
| `mapSearchRef`, `mapStatsRef` | click-outside refs no longer needed |

### Variables to add

| Variable | Type | Purpose |
|---|---|---|
| `selectedLocationId` | `string \| null` | Single source of truth for map + detail |

### Variables to keep (unchanged)

`locations`, `models`, `users`, `loading`, `submitting`, `message`, `error`,
`activeModal`, `assetFormError`, `editingOperator`, `detailModel`,
`siteId`, `siteName`, `siteMetadata`, `buildingId`, `buildingName`,
`buildingSiteId`, `buildingMetadata`, `locationQuery`,
`locationStatusFilter`, `locationPage`, `locationSearchLoading`,
`searchedLocations`

**Result: 22 → 14 state variables**

---

## 4. Logic Layer — No Changes

These functions are correct and stay exactly as written:

- `locationPoint(location)` — extracts `{lat, lon}` from metadata
- `osmEmbedUrl(point, zoom)` — builds OSM iframe src
- `osmLocationUrl(point, zoom)` — builds OSM external link
- `modelsForLocation(location)` — returns matching registered models
- `modelMatches`, `modelTask`, `modelAppliesGlobally`, `modelHasSpecificLocationScope`
- `assignedOperatorsForLocation(location)` — returns operators with assignment type
- `refresh()` — loads locations + models + users
- `toggleLocationArchive(location)` — patches archive flag, updates local state
- `handleCreateSite`, `handleCreateBuilding` — form submit handlers
- `run(action, fn)` — generic submitting wrapper
- All helper formatters: `titleCase`, `shortJson`, `formatCoordinate`,
  `statusLabel`, `operatorStatusTone`, `metadataString`, `anomalyHref`

---

## 5. Implementation Tasks

### Phase 1 — State Simplification

**Task 1.1** Remove dead/replaced state declarations:
```ts
// DELETE these
const [galleryOpen, setGalleryOpen] = useState(false);
const [mapStatsOpen, setMapStatsOpen] = useState(false);
const [mapQuery, setMapQuery] = useState("");
const [mapDropdownOpen, setMapDropdownOpen] = useState(false);
const [mapSearchedLocations, setMapSearchedLocations] = useState<LocationOption[] | null>(null);
const [mapSearchLoading, setMapSearchLoading] = useState(false);
const [detailTarget, setDetailTarget] = useState<DetailTarget>(null);
const mapSearchRef = useRef<HTMLDivElement | null>(null);
const mapStatsRef = useRef<HTMLDivElement | null>(null);
```

**Task 1.2** Add `selectedLocationId`:
```ts
const [selectedLocationId, setSelectedLocationId] = useState<string | null>(null);
```

**Task 1.3** Derive `selectedLocation` and `selectedPoint` from `selectedLocationId`:
```ts
const selectedLocation = selectedLocationId ? (locationById.get(selectedLocationId) ?? null) : null;
const selectedPoint = selectedLocation ? locationPoint(selectedLocation) : null;
```

**Task 1.4** Remove the two `useEffect` blocks that handled
`mapDropdownOpen` and `mapStatsOpen` click-outside listeners.

**Task 1.5** Remove the `mapLocationById` memo (was only needed for map
dropdown reconciliation). The `locationById` map already covers this.

**Task 1.6** Remove `DetailTarget` and `AssetModal`-related `detailTarget`
type. Keep `AssetModal = "site" | "building" | null`.

**Task 1.7** Update `mapSearchResults`, `activeMapLocationId`,
`selectedMapLocation`, `selectedMapPoint`, `selectedMapModels`,
`selectedMapChildren`, `selectedMapOperators` — these were derived from
the old map search state. Replace them all with a single derivation from
`selectedLocationId`:

```ts
const selectedModels = selectedLocation ? modelsForLocation(selectedLocation) : [];
const selectedChildren = selectedLocation
  ? locations.filter((item) => item.parent_id === selectedLocation.id)
  : [];
const selectedOperators = canManageAssets
  ? assignedOperatorsForLocation(selectedLocation)
  : [];
```

---

### Phase 2 — KPI Strip

Replace the stats popover with a persistent grid of stat cards above the
main workspace.

**Task 2.1** Add a KPI strip section in JSX between the page head and the
main workspace:

```tsx
<div className="asset-kpi-strip">
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
  {canViewModelCoverage && (
    <div className="asset-stat-card">
      <span>Model-covered</span>
      <b>{modelCoveredLocationCount}</b>
      <small>Production model match</small>
    </div>
  )}
</div>
```

**Task 2.2** Add CSS class `.asset-kpi-strip`:
```css
.asset-kpi-strip {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 14px;
    margin-bottom: 22px;
}
```
The child cards reuse the existing `.asset-stat-card` and
`.asset-stat-card.is-primary` classes unchanged.

---

### Phase 3 — Location Browser (Left Panel)

This replaces the gallery modal entirely. It becomes an inline scrollable
panel on the left side of the workspace.

**Task 3.1** Add a `<Card>` titled "Locations" as the left column of
`.assets-workspace` (new grid container — see Phase 5).

**Task 3.2** Inside the card body, add the toolbar (search + filter tabs).
These already exist in the gallery modal; move them inline:

```tsx
<div className="asset-toolbar">
  <div className="asset-toolbar-controls">
    <div className="asset-search">
      <Icon name="search" />
      <input
        value={locationQuery}
        onChange={(e) => { setLocationQuery(e.target.value); setLocationPage(1); }}
        placeholder="Search location, type, status"
      />
    </div>
    <div className="asset-filter-row">
      {(["all", "active", "archived"] as const).map((s) => (
        <button
          key={s}
          className={locationStatusFilter === s ? "is-selected" : ""}
          type="button"
          onClick={() => { setLocationStatusFilter(s); setLocationPage(1); }}
        >
          {s === "all" ? "All" : s === "active" ? "Active" : "Archived"}
        </button>
      ))}
    </div>
  </div>
  <span className="asset-search-help">
    {locationSearchLoading
      ? "Searching..."
      : locationQuery.trim()
        ? `${filteredLocations.length} results`
        : `${locations.length} locations`}
  </span>
</div>
```

**Task 3.3** Render the location list as grouped rows (sites with their
buildings indented):

```tsx
<div className="asset-browser-list">
  {pagedLocations.map((location) => (
    <button
      key={location.id}
      type="button"
      className={[
        "asset-browser-row",
        !isSiteLocation(location) && "is-child",
        selectedLocationId === location.id && "is-selected",
        location.archived && "is-archived",
      ].filter(Boolean).join(" ")}
      onClick={() => setSelectedLocationId(location.id)}
    >
      <span className="asset-browser-icon">
        <Icon name={isSiteLocation(location) ? "map" : "building"} />
      </span>
      <span className="asset-browser-info">
        <b>{displayLocationName(location.name, location.id)}</b>
        <small>{location.id}</small>
      </span>
      <span className="asset-browser-meta">
        <span className={`badge ${location.archived ? "badge-neutral" : "badge-resolved"}`}>
          {location.archived ? "Archived" : "Active"}
        </span>
        {mappedLocationById.has(location.id) && (
          <span className="asset-coord-dot" title="Has coordinates" />
        )}
      </span>
    </button>
  ))}
  {filteredLocations.length === 0 && (
    <div className="asset-empty">No locations match the selected filters.</div>
  )}
</div>
```

**Task 3.4** Add the pager below the list. Reuse the existing `.pager`
markup unchanged from the gallery modal.

**Task 3.5** Sort `pagedLocations` so sites appear before their buildings
and buildings are grouped under their site. Change the sort logic in
`filteredLocations` (or add a `sortedFilteredLocations` memo):

```ts
const sortedFilteredLocations = useMemo(() => {
  const sites = filteredLocations.filter(isSiteLocation);
  const buildings = filteredLocations.filter((l) => !isSiteLocation(l));
  const result: LocationOption[] = [];
  for (const site of sites) {
    result.push(site);
    result.push(...buildings.filter((b) => b.parent_id === site.id));
  }
  // Orphan buildings (no matching site in current filter)
  const siteIds = new Set(sites.map((s) => s.id));
  result.push(...buildings.filter((b) => !b.parent_id || !siteIds.has(b.parent_id)));
  return result;
}, [filteredLocations]);
```
Use `sortedFilteredLocations` instead of `filteredLocations` for
`pagedLocations`, `totalLocationPages`, range calculations.

---

### Phase 4 — Map + Detail Panel (Right Panel)

This replaces the current full-page map card and dead drawer.

**Task 4.1** Add a `<Card>` for the map+detail right column. The card
title can be dynamic: the selected location name, or "Asset Map" if
nothing selected.

**Task 4.2** Map iframe — reuse existing iframe markup, but source is now
driven by `selectedPoint ?? mapCenter`:

```tsx
<div className="asset-map-frame-wrap">
  {(selectedPoint ?? mapCenter) ? (
    <iframe
      className="asset-map-frame"
      title={selectedLocation
        ? `${displayLocationName(selectedLocation.name, selectedLocation.id)} map`
        : "Asset map"}
      src={osmEmbedUrl(selectedPoint ?? mapCenter!, selectedPoint ? 17 : 3)}
      loading="lazy"
      referrerPolicy="no-referrer-when-downgrade"
    />
  ) : (
    <div className="asset-empty" style={{ height: "100%" }}>
      No coordinates found in location metadata yet.
    </div>
  )}
</div>
```

**Task 4.3** Detail section below the map. Show when `selectedLocation`
is not null; otherwise show empty state:

```tsx
{selectedLocation ? (
  <div className="asset-detail-body">

    {/* Header */}
    <div className="asset-detail-hd">
      <h3>{displayLocationName(selectedLocation.name, selectedLocation.id)}</h3>
      <p>{selectedLocation.id}</p>
    </div>

    {/* Fact grid */}
    <div className="asset-detail-facts">
      <div><span>Type</span><b>{titleCase(selectedLocation.location_type)}</b></div>
      <div><span>Site</span><b>{isSiteLocation(selectedLocation) ? selectedLocation.id : selectedLocation.parent_id ?? "—"}</b></div>
      <div><span>Status</span><b>{selectedLocation.archived ? "Archived" : "Active"}</b></div>
      <div><span>Coords</span><b>{selectedPoint ? `${formatCoordinate(selectedPoint.lat)}, ${formatCoordinate(selectedPoint.lon)}` : "No coordinates"}</b></div>
    </div>

    {/* Actions */}
    <div className="asset-detail-actions">
      <button className="btn btn-primary btn-small" type="button"
        onClick={() => router.push(anomalyHref(selectedLocation))}>
        <Icon name="pulse" /><span>Anomaly</span>
      </button>
      {selectedPoint && (
        <a className="btn btn-secondary btn-small"
          href={osmLocationUrl(selectedPoint)} target="_blank" rel="noreferrer">
          <Icon name="external" /><span>Open OSM</span>
        </a>
      )}
      {canManageAssets && (
        <button className="btn btn-secondary btn-small" type="button"
          disabled={submitting === `archive-${selectedLocation.id}`}
          onClick={() => void toggleLocationArchive(selectedLocation)}>
          <Icon name="flag" />
          <span>{selectedLocation.archived ? "Restore" : "Archive"}</span>
        </button>
      )}
    </div>

    {/* Operators — admin only */}
    {canManageAssets && (
      <div className="asset-detail-section">
        <span className="asset-summary-label">Assigned Operators</span>
        <div className="asset-operator-list">
          {selectedOperators.map(({ user }) => (
            <div className="asset-operator-row" key={user.id}>
              <span className={`user-status-dot ${operatorStatusTone(user.status)}`}
                aria-label={statusLabel(user.status)} />
              <span><b>{user.full_name}</b><small>{user.email}</small></span>
              <button className="btn btn-small" type="button"
                onClick={() => setEditingOperator(user)}>
                <Icon name="settings" /><span>Edit</span>
              </button>
            </div>
          ))}
          {selectedOperators.length === 0 && (
            <span className="asset-operator-empty">No operators assigned.</span>
          )}
        </div>
      </div>
    )}

    {/* Models — admin + AI engineer */}
    {canViewModelCoverage && (
      <div className="asset-detail-section">
        <span className="asset-summary-label">Models</span>
        <div className="asset-detail-list compact">
          {selectedModels.map((model) => (
            <button key={model.name} className="asset-detail-list-action"
              type="button" title={model.name}
              onClick={() => setDetailModel(model)}>
              {displayModelName(model.name)}
            </button>
          ))}
          {selectedModels.length === 0 && <span>No matching models</span>}
        </div>
      </div>
    )}

    {/* Children */}
    <div className="asset-detail-section">
      <span className="asset-summary-label">Child Assets</span>
      <div className="asset-detail-list compact">
        {selectedChildren.slice(0, 6).map((item) => (
          <button key={item.id} className="asset-detail-list-action" type="button"
            onClick={() => setSelectedLocationId(item.id)}>
            {displayLocationName(item.name, item.id)}
          </button>
        ))}
        {selectedChildren.length === 0 && <span>No child locations</span>}
      </div>
    </div>

    {/* Metadata */}
    <div className="asset-detail-section">
      <span className="asset-summary-label">Metadata JSON</span>
      <pre className="asset-json">{shortJson(selectedLocation.metadata)}</pre>
    </div>

  </div>
) : (
  <div className="asset-detail-empty-state">
    <Icon name="map" />
    <b>No location selected</b>
    <small>Pick a location from the list to see its details here.</small>
  </div>
)}
```

---

### Phase 5 — CSS Changes

#### New classes to add

```css
/* Main two-column workspace */
.assets-workspace {
    display: grid;
    grid-template-columns: minmax(300px, 38%) minmax(0, 1fr);
    align-items: start;
    gap: 24px;
}

/* KPI strip (replaces .asset-summary-grid which was unused) */
.asset-kpi-strip {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 14px;
    margin-bottom: 22px;
}

/* Location browser list */
.asset-browser-list {
    display: grid;
    gap: 6px;
    max-height: 520px;
    overflow-y: auto;
    padding-right: 2px;
}

/* Location browser row */
.asset-browser-row {
    display: grid;
    grid-template-columns: 28px minmax(0, 1fr) auto;
    align-items: center;
    gap: 10px;
    min-height: 52px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-2);
    color: var(--ink-2);
    text-align: left;
    cursor: pointer;
    transition: border .12s, background .12s;
}
.asset-browser-row:hover {
    border-color: var(--accent-border);
    background: var(--accent-soft);
    color: var(--ink);
}
.asset-browser-row.is-selected {
    border-color: var(--accent-border);
    background: var(--accent-soft);
    color: var(--ink);
    box-shadow: var(--shadow-md);
}
.asset-browser-row.is-child {
    margin-left: 22px;
    border-left: 2px solid var(--accent-border);
}
.asset-browser-row.is-archived {
    opacity: 0.65;
}

/* Browser row internals */
.asset-browser-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--accent-600);
}
.asset-browser-icon svg { width: 15px; height: 15px; }

.asset-browser-info {
    display: grid;
    gap: 2px;
    min-width: 0;
}
.asset-browser-info b {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
    color: var(--ink);
    line-height: 1.3;
}
.asset-browser-info small {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 11.5px;
    color: var(--muted);
    line-height: 1.25;
}

.asset-browser-meta {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
}

.asset-coord-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--accent-600);
    flex-shrink: 0;
    title: "Has coordinates";
}

/* Map frame wrapper */
.asset-map-frame-wrap {
    position: relative;
    overflow: hidden;
    height: 280px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-2);
    margin-bottom: 18px;
}
.asset-map-frame-wrap iframe {
    width: 100%;
    height: 100%;
    border: 0;
}

/* Detail body (right panel below map) */
.asset-detail-body {
    display: grid;
    gap: 18px;
}

.asset-detail-hd {
    display: grid;
    gap: 3px;
    min-width: 0;
}
.asset-detail-hd h3 {
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 16px;
    color: var(--ink);
    letter-spacing: 0;
}
.asset-detail-hd p {
    margin: 0;
    font-size: 12px;
    color: var(--muted);
}

.asset-detail-facts {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
}
.asset-detail-facts > div {
    display: grid;
    gap: 3px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-2);
}
.asset-detail-facts span {
    font-size: 10.5px;
    font-weight: 720;
    text-transform: uppercase;
    letter-spacing: .04em;
    color: var(--muted);
    line-height: 1.15;
}
.asset-detail-facts b {
    font-size: 13px;
    color: var(--ink);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.asset-detail-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}

.asset-detail-section {
    display: grid;
    gap: 10px;
}

.asset-detail-empty-state {
    display: grid;
    gap: 8px;
    padding: 32px 16px;
    text-align: center;
    justify-items: center;
    color: var(--muted);
}
.asset-detail-empty-state svg { width: 28px; height: 28px; opacity: .4; }
.asset-detail-empty-state b { font-size: 14px; color: var(--ink-2); }
.asset-detail-empty-state small { font-size: 12px; }
```

#### Responsive overrides to add

```css
@media (max-width: 960px) {
    .assets-workspace {
        grid-template-columns: 1fr;
    }
    .asset-browser-list {
        max-height: 360px;
    }
    .asset-kpi-strip {
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }
}

@media (max-width: 640px) {
    .asset-kpi-strip {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .asset-browser-row.is-child {
        margin-left: 12px;
    }
    .asset-detail-facts {
        grid-template-columns: 1fr;
    }
}
```

#### Classes to delete (no longer rendered)

```
.asset-map-workspace
.asset-map-actions
.asset-map-stats-wrap
.asset-map-stats-popover
.asset-map-stats-head
.asset-map-stats-head b / small
.asset-map-stats-grid
.asset-map-stats-foot
.asset-map-command
.asset-map-search-wrap
.asset-map-search
.asset-map-dropdown (and all children: button, svg, span, b, small, em)
.asset-map-no-results
.asset-map-content
.asset-map-main
.asset-map-detail-panel
.asset-map-detail-head
.asset-map-detail-facts (old version)
.asset-map-detail-actions (old version)
.asset-map-anomaly-action / osm-action / archive-action
.asset-map-detail-section (old version)
.asset-map-detail-empty
.asset-gallery-modal
.asset-gallery-modal .app-modal-body
.asset-gallery (tile grid)
.asset-tile / asset-tile-head / asset-tile-icon / asset-tile b / asset-tile span
.asset-tile-meta / asset-tile-stats
.asset-detail (drawer class)
.asset-detail .drawer-head h3 / span
.asset-summary-grid (was defined but never used in render)
.asset-summary-card / asset-summary-value / asset-summary-foot
.assets-grid
.assets-layout (replaced by .assets-workspace)
```

Keep: `.asset-stat-card`, `.asset-stat-card.is-primary`, `.asset-search`,
`.asset-toolbar`, `.asset-toolbar-controls`, `.asset-filter-row`,
`.asset-search-help`, `.asset-json`, `.asset-empty`, `.asset-operator-list`,
`.asset-operator-row`, `.asset-operator-empty`, `.asset-detail-list`,
`.asset-detail-list-action`, `.asset-osm-link`, `.asset-form`, `.asset-modal`,
`.asset-summary-label`

---

### Phase 6 — Remove Dead Code

**Task 6.1** Delete the entire gallery `Modal` block (lines ~842–951):
```tsx
{galleryOpen && (
  <Modal title="Location Gallery" ...>
    ...
  </Modal>
)}
```

**Task 6.2** Delete the stats popover inside the current map card actions.

**Task 6.3** Delete the `detailTarget` drawer block (lines ~1015–1113):
```tsx
{detailTarget && (
  <>
    <button className="overlay" ... />
    <aside className="drawer asset-detail" ...>
      ...
    </aside>
  </>
)}
```

**Task 6.4** Delete the `DetailTarget` type definition (line ~24).

**Task 6.5** Delete unused memos: `mapLocationById`, `mapSearchResults`,
`activeMapLocationId`, `selectedMapLocation`, `selectedMapPoint`,
`selectedMapModels`, `selectedMapChildren`, `selectedMapOperators`.

**Task 6.6** Delete the `mapQuery` search `useEffect` (lines ~367–392).

**Task 6.7** Delete the two click-outside `useEffect` blocks for
`mapDropdownOpen` and `mapStatsOpen`.

---

## 6. File Change Summary

| File | Change type | Scope |
|---|---|---|
| `assets-page.tsx` | Rewrite render | Replace ~560 JSX lines with ~350; logic functions untouched |
| `assets-page.tsx` | Remove state | Delete 8 state vars + 2 refs |
| `assets-page.tsx` | Add state | Add `selectedLocationId` |
| `assets-page.tsx` | Add memo | `sortedFilteredLocations` |
| `assets-page.tsx` | Remove memos | 6 map-search derived values |
| `assets-page.tsx` | Remove useEffects | 3 (click-outside × 2, map search) |
| `globals.css` | Add | ~120 lines (new classes) |
| `globals.css` | Delete | ~200 lines (removed classes) |
| `globals.css` | Update | Responsive overrides for new layout |

**Net result:** ~250 fewer lines of JSX, ~80 fewer lines of CSS.

---

## 7. Implementation Order

1. `[Phase 1]` State simplification — do this first so the file compiles clean before touching JSX
2. `[Phase 5]` Add new CSS classes — add before rendering so no FOUC during dev
3. `[Phase 2]` KPI strip — easiest, standalone section
4. `[Phase 3]` Location browser — left panel; test search + filter + pagination
5. `[Phase 4]` Map + detail panel — right panel; test selection, archive, operators, models
6. `[Phase 6]` Delete dead code — gallery modal, stats popover, drawer
7. `[Phase 5]` Delete old CSS classes — after confirming none still referenced

---

## 8. Open Questions

| # | Question | Default if not answered |
|---|---|---|
| 1 | Should child (building) rows be collapsible under their site, or always expanded? | Always expanded (simpler; pagination controls density) |
| 2 | Should the map card have a "Search map" input for map-only search separate from the list? | No — list search drives both; no separate map search |
| 3 | Should clicking a child asset in the detail panel's "Child Assets" section navigate to that child in the list? | Yes — call `setSelectedLocationId(item.id)` |
| 4 | Should the "Open OSM" link in the header be retained for the map centroid? | No — only show "Open OSM" in the detail panel for the selected location |
| 5 | Should the map panel show even when the right column is the active pane on mobile? | Yes — map is above the detail, so it always shows; list below |
