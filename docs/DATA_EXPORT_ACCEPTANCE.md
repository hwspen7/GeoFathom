# Data and Export acceptance contract

The two top-level workspaces provide one end-to-end workflow: inspect source
files, choose layers and field conversions, validate, atomically persist, inspect
the export scope, deliver a GIS dataset, and restore a checksummed project.

## Delivered capabilities

| Area | Contract |
| --- | --- |
| Inputs | GeoJSON/JSON, multi-layer GPKG, KML, GPX, multi-layer zipped SHP, CSV (XY or WKT), existing GeoTIFF workflow |
| Import preflight | Source layers, counts, field names/types and declared CRS; configurable CSV encoding/separator, coordinates, EPSG fallback, field mapping and conversions |
| Batch | 1–20 files, 128 MiB/file, 512 MiB/batch, 100,000 valid features and 4 million vertices/batch; each individual geometry remains bounded to 20,000 coordinates |
| Validation | Strict batch rejection by default; explicit skip mode produces a downloadable per-file, layer and row report; over 1,000 invalid rows rejects the source |
| Persistence | Every batch is one SQL transaction. A failed/cancelled transaction saves no features or newly created layers. Its success receipt commits in that same transaction, even if the worker exits immediately afterward |
| Jobs | Progress, cooperative cancellation before commit, persisted result/report download; a late cancel after successful commit cannot claim that saved data disappeared |
| Vector output | GeoJSON, multi-layer GPKG, multi-layer SHP ZIP, KML, GPX (points/lines), CSV including all attributes/WKT and optional measured quantities |
| Scopes | Selection, local drawings, detected areas, entire saved project, one saved layer, saved features intersecting the current geographic map extent; API additionally accepts explicit feature IDs |
| Output configuration | Explicit supported horizontal 2D EPSG, selected fields, optional coordinate decimals; collapsing/invalid precision is rejected |
| Integrity | Entire saved scopes are read from a coherent database snapshot, independently of the 200-row workspace page; source feature/layer ownership is validated |
| Reports | Server-measured scientific JSON across the entire scope; existing printable PDF and actual analysis GeoTIFF retain their dedicated engines |
| Portable project | ZIP with exact member sizes/SHA-256, saved features, original properties/names/sources, layers, styles, CRS, edit history, optionally explicitly selected source GeoTIFFs; raster IDs are remapped on restore |
| Restore | New empty target only, checksum/schema/geometry checks before writes, transactional saved vector state, removal of installed raster assets if restore fails |
| Lifecycle | Abandoned staged uploads expire after 24 hours (active import jobs exempt), delivery artifacts after 7 days; per-project exchange storage budget 2 GiB |
| Access | Project-scoped reads, editor imports, no cross-project staged upload or output access; raster installation retains the existing operator/local-import policy |

## Fidelity and interoperability

- WGS84 remains authoritative editing storage. GPKG, SHP and CSV can deliver
  projected coordinates; GeoJSON, KML, GPX and measurement reports use WGS84.
  Horizontal reprojection preserves the source Z ordinate without claiming a
  vertical datum transformation.
- GeoJSON retains JSON properties directly. GPKG exposes native columns, with a
  documented `_gf_json` column/metadata retaining nulls, absent fields, nested
  JSON, booleans and large integers exactly for GeoFathom round trips. Edits to
  ordinary native columns made by an external GIS take precedence over the
  companion; unchanged fields retain their exact original types.
- SHP imposes short names and limited types. The ZIP contains geometry-family
  layers, aliased native fields and `geofathom.json` with original field names,
  exact properties and component checksums. Keep that companion when importing
  back. A changed native component with an unchanged companion is rejected
  instead of silently restoring outdated fields.
- KML includes conventional ExtendedData and GPX includes standard geometry;
  namespaced extensions retain exact JSON attributes and source layer names.
  External tools may remove these optional extensions.
- CSV represents null as empty text and nested values as JSON text. Configure
  the WKT column, CRS and types on reimport. Formula-like text is escaped for
  spreadsheet use. Choose GPKG/GeoJSON when exact native attribute types matter.
- Project ZIP packages saved project data, not unsaved browser drawings,
  transient analysis caches, credentials, server jobs, external service content
  or installed model binaries. Source accuracy is unchanged by export.

## Executable acceptance

`tests/test_exchange.py` exercises real GDAL/JSON/XML round trips, native
attribute types, multiple source layers and geometry families, projected output,
field selection, CSV conversions and formula escaping, 620-row imports/exports,
scientific reports and job downloads, strict/skip policy, rollback and live
cancellation, durable receipts, project access boundaries, checksummed package
restore, styles/CRS/revisions and actual source GeoTIFFs.

`web/src/dataExport.test.tsx` covers UI scope/field submission and stale request
suppression for project A–B–A. `web/e2e/dataset-exchange.spec.ts` uses real Chromium,
real uploads and downloads, 620-row CSV and projected GPKG reimport, CSV field
mapping/error reports and project ZIP restoration. Existing E2E workflows remain
part of the regression suite, with zero retries.

Run:

```sh
python scripts/run_acceptance.py -q
cd web
npm run build
npm test
npm run test:e2e
```

A pass of one layer does not imply another layer passed. Browser checks must run
in an environment that permits Chromium processes and its IPC sockets.

The repository-wide `quality-targets` coverage threshold job is currently
explicitly skipped by project decision. Coverage measurement, reports and the
recorded target comparisons remain available. Build, functional, data integrity,
native safety, PostGIS and serial/concurrent browser checks still run and must
pass. A green workflow under this policy does not assert that coverage targets
have been reached; removing the job-level false condition re-enables that gate.
