# Terrain maintenance handoff and release criteria — 2026-11-22

This file records the post-upgrade **capabilities, assumptions and open gates**.
It is not a certification, and a green UI smoke test is not numerical validation.

## Delivered capabilities

- Local projected, north-up meter DEM ingestion; source scale/offset validation.
- Local DEM clip, resample and first-source-precedence mosaic in bounded
  processing windows. The output is a new GeoTIFF; source files remain intact.
- DEM grid registration is inherited from the primary dataset rather than
  forced onto arbitrary whole-coordinate origins.
- DEM preparation supports up to 32 million output cells and 8192 pixels per
  axis; it uses 512x512 processing windows with cancellation checkpoints.
- Basic slope/aspect statistics use a C++/NumPy Horn kernel on small grids
  and a halo-correct streaming Horn path on larger grids (same 32M limit).
- Advanced surfaces, contours, drainage, visibility, earthworks, cross
  sections, DEM difference and WebGL2 terrain preview remain available.
- DEM difference keeps signed physical elevations and checks the named
  vertical datum; its visual classes have a true zero-change center.
- Priority-flood drainage conditions a temporary working DEM, preserves
  original source pixels and keeps physical fill depth/volume distinct from
  the one-ULP gradient used to resolve flat routing.
- The primary and reference input DEM identities are recorded with run
  metadata. Browser-local IndexedDB caches complete result payloads
  (profile, raster/GeoTIFF, mesh and cross sections) per project, up to
  24 current versions; automatically restored results start hidden.
- Browser result caching has a per-record limit (40 million JSON characters).
  Failures/quotas are disclosed to the user rather than truncating output.
  Metadata receipts remain separate. Cache is not a portable archive.
- Changing project, deleting an analysis result, or replacing an unsaved live
  result cannot silently retain its currently displayed overlay.

## Important boundaries and scientific limitations

1. **Native accuracy:** requested output grid size does not establish actual
   source DEM resolution or vertical accuracy. Copernicus GLO-30 is a DSM and
   USGS 3DEP is a bare-earth model; use provenance and source epochs.
2. **Vertical reference:** metadata comparisons reject conflicting known
   vertical datum names, but missing labels remain unverified. A matching name
   is not proof of comparable survey control.
3. **Spatial extent:** DEM processing and basic slope can use 32M cells;
   advanced surfaces use independent smaller grid limits (typically 8M),
   contours ~1M/64 levels, and visibility ~262k cells/10km.
4. **Hydrology:** local D8 + priority flood, with study-area/no-data boundaries
   treated as outlets. Results do not include unknown upslope catchments outside
   the selected raster. They are not hydrological engineering certification.
5. **Visibility:** local nearest-cell rays; optional effective-Earth curvature
   and atmospheric refraction. Structures/vegetation depend on whether the
   input is DEM or DSM.
6. **Earthworks:** single reference plane or DEM difference volumes are
   cell-center estimates, not field surveying or contractor cut/fill quantities.
7. **Terrain preview:** 3D mesh has a decimated representation rather than
   a full multiscale terrain LOD service.
8. **Local persistence:** IndexedDB is bound to one browser/device and subject
   to browser quotas. Always export GeoTIFF, GeoJSON or result data for
   durable, portable preservation.
9. **NoData:** unknown source cells are never synthesized as real heights,
   and a missing observer/routing neighborhood can make an answer undefined.

## Required release checks

- [ ] All GitHub Actions jobs pass on the **same final commit**:
      Python, Windows, Web, Browser, PostGIS, native-coverage,
      quality-measurement and quality-targets.
- [ ] Do not reduce coverage targets or modify scientific assertions to force
      passing tests. The Python/Web coverage gates remain unchanged.
- [ ] Compare the tiled Horn and full-grid Horn results on continuous and
      NoData-interrupted DEMs, including block seams and cancellation.
- [ ] Validate tile-based mosaic resampling against an independently prepared
      GeoTIFF, including nodata edges and mismatched CRS.
- [ ] Validate a flat plateau and a nested pit: drainage may use numerical
      tie-breaking, while physical fill volume remains unchanged on flat DEM.
- [ ] Check reload, deletion, cancellation, project isolation and quota
      errors for cached **full** analysis results.
- [ ] Test large DEM source windows near the current per-operation grid caps.
- [ ] Re-run the complete browser E2E suite (not only Terrain-specific tests)
      after final changes to map interactions.

## Recommended post-Terrain work (not yet delivered)

- A portable project-asset archive for derived scientific rasters and
  reproducible processing recipes, independent of browser storage.
- Fully tiled advanced surface/raster algorithms, rather than the current
  operation-specific limits.
- Additional hydrology models (breach, MFD / D-infinity) and multi-observer
  visibility, if supported by real research use cases.
- Independent numerical validation against trusted reference GIS datasets.

**Maintenance decision:** The module may enter routine maintenance only
after the final SHA meets the test gates. Code coverage or partial CI success
is not by itself a claim of full feature completeness.
