# Geospatial selection lifecycle audit — 2026-11-22

## Object identity and ownership

- **Retained places** are project-scoped references stored in browser local storage. A search with multiple candidates does not silently choose the first. Confirming a place retains it, and a **Remove pinned ...** control is required to delete the reference. Selecting another feature or beginning a tool cannot silently delete it.
- **Active selection** controls the Inspector and editing. Deselect may clear this temporary focus, but it does not delete retained locations, saved project features, independent profile lines or existing local draft objects.
- **New survey sketches** keep the previous selected shape visible while drawing. A successful Finish can make the new draft active; the prior searched area remains a retained reference and saved/scratch features remain intact.
- **Terrain profile line** is an independent LineString used only by the profile/cross-section workflows. Drawing, canceling, selecting a DEM or running Terrain never replaces the searched airport polygon. Existing saved LineStrings are accepted if no independent profile line is set.
- **Explicit deletion** of a retained search place uses the Remove button; explicit deletion of the terrain profile line uses Remove profile line. Removing one does not remove the other.
- **Project switches** change the active scope, hiding but not deleting another project's pinned search places.

## Implicit reset audit

| Entry point | Active focus change | Retained search place | Profile line |
| --- | --- | --- | --- |
| Search one result | select result | add | preserve |
| Search several results | no automatic choice | preserve | preserve |
| Click blank map | preserve | preserve | preserve |
| Click saved or pinned object | change active focus | preserve | preserve |
| Switch toolbar / Terrain | preserve | preserve | preserve |
| Draw profile line | preserve | preserve | replace only on successful Finish |
| Cancel / Escape | stop interaction | preserve | preserve |
| Deselect | clear active focus | preserve | preserve |
| Draw general survey shape | preserve during sketch; activate new draft on Finish | preserve | preserve |
| Delete local/project geometry | clear deleted active focus | preserve | preserve |
| Remove retained place | clear the active place if needed | remove only chosen place | preserve |
| Remove profile line | preserve | preserve | remove line |
| Undo / Redo | adjust selected draft/history | preserve | preserve |
| Switch project | change project focus | retained per project | in-progress line cleared with workspace |

## Tests

- `web/src/pinnedPlaces.test.ts`: distinct references retained, no silent eviction and explicit removal.
- `web/e2e/place-terrain-continuity.spec.ts`: CMH search, map clicks, Terrain activation, drawn profile finish, independent line and region, browser reload, explicit removal; point-only search.
- `web/e2e/terrain-workbench.spec.ts`: existing saved LineString profile compatibility.

## Engineering boundaries

A searched place that provides only coordinates is not a surveyed polygon. The map may focus on the point and download a DEM in the visible viewport; area analysis still requires a real polygon or the DEM extent.

Persistent reference pins are a browser-local project workspace feature. Moving to a different browser or clearing site storage does not transfer these pins; server project features should be saved to the project for portable persistence.

## Search-derived campus boundaries and coordinates (2026-11-22)

- Search results can contain disconnected OSM MultiPolygon parcels (e.g., a main university campus plus distant land). Treat each outer polygon as a separately selectable study parcel; keep original source intact in Pinned places.
- For a multipolygon, default to the connected parcel containing or nearest the geocoder's reference coordinate. Explicit **Study area parcel** dropdown allows selecting the full OSM geometry or any individual parcel.
- DEM target bounds, orange preview rectangle and area analysis derive from the **currently chosen study parcel**, not the entire multipolygon once a component is chosen. Remote detached parcels must no longer inflate main-campus download budgets.
- All selected boundary vertices appear as compact green point markers. The current node appears orange. **Edit boundary nodes** opens the real drag handles and midpoint insertion; the Inspector supports exact WGS84 longitude and latitude edits and validates them with the existing GIS measurement API.
- Clicking a vertex to read its coordinates is non-mutating. The original OSM source remains unchanged; successful modifications are saved as separate, editable, local scratch features. A user must explicitly remove a pinned original or local copy.
- Both unit and browser tests cover far-north campus outliers, actual geometry nodes and source-retention invariants. Live OSM data and provider acquisition still require on-machine verification.
