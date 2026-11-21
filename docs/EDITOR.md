# Precision survey editor

GeoFathom combines browser-native editing with server-side geodesic
measurement and C++ accelerated geometry operations. The editor follows
patterns found in QGIS/ArcGIS, but is not a land survey instrument.

## Immediate editing and measurement

Open a map and choose **Survey & geometry editor**:

- **Polygon**: click at least three corners, then **Finish**.
- **Line**: click two or more points, then **Finish**.
- **Rectangle**: click two opposite corners and finish.
- **Circle**: click a center and a point on the radius and finish. The backend
  creates a geodesic circle with 72 vertices by default.
- **Vertices**: enable editing for the current polygon. Drag a large white
  handle to reposition a corner; drag a smaller blue midpoint to insert a
  vertex. Right-click a corner to delete it. Double-click near an edge to
  insert a corner along that edge. Minimum ring sizes are enforced.
- **Move**: drag inside the selected polygon to translate it.
- **Snap ON/OFF**: browser-local snapping to visible layer vertices and
  edges within a 12-pixel threshold. The backend also offers projected-meter
  snapping in C++ for programmatic GIS queries.
- **Undo/Redo**: button or Ctrl/Command+Z; redo with Ctrl/Command+Shift+Z or
  Ctrl+Y. Browser history holds the last 100 committed geometry snapshots.
- **Measurement**: during dragging, the browser displays a clearly marked
  spherical *estimate* and a list of edge distances. On release, FastAPI
  validates geometry and replaces that estimate with an ellipsoidal WGS84
  result from PyProj.
- **Units**: m², hectares, km² and 亩 can be selected without changing
  the underlying geodesic measurement.

If a vertex move creates a self-intersection, the final server validation
rejects it and the browser restores the last valid shape.

## Constructive geometry

- **Cut hole**: select an existing polygon, click a fully contained
  polygon, then Finish. The area excludes the interior hole.
- **Split line**: select a polygon, click two or more points forming a
  cutting line, then Finish. Both parts are returned and can be saved as
  separate features in the active project.
- **Union / Subtract / Intersect**: select a polygon and another saved
  polygon in the overlay control. Results are validated with Shapely and
  measured on WGS84.
- **Duplicate**: copy the currently selected geometry in the browser,
  or duplicate a saved feature from the project panel.
- **Exact construction**: enter longitude and latitude coordinates to
  add a drawing vertex, define opposite rectangle corners, specify a
  circle radius in meters, or create a line with bearing and distance.
- **Line simplification**: /edit/simplify accepts up to 20,000 coordinates
  and a 0–500 m tolerance. Its C++ Ramer-Douglas-Peucker kernel runs when
  compiled, otherwise the Shapely fallback remains available.

Large, global and antimeridian-crossing geometries require a dedicated CRS
and topology workflow; do not use the local editor beyond its guardrails.

## Project layers and version history

Use **Projects & saved geometry**:

1. Create a project and add named layers with individual colors.
2. Toggle each layer's visibility and lock state. Select a layer to choose
   where newly saved features will be stored.
3. Save an outline, reopen it and make a change. **Update feature** writes
   a new immutable revision. Changes are protected by an optimistic
   revision number so a stale edit cannot silently overwrite another.
4. Click **Versions** to view timestamps and measured areas. Restore any
   listed earlier revision. Restore creates a *new* revision, preserving
   the rest of the history.
5. Use Copy to duplicate saved geometries, or export an ordinary GeoJSON
   FeatureCollection. Geometries retain their source metadata.

Layer locks are checked by the server for editing, duplication, saving and
deletion. Layers are stored in SQLite per project; the API exposes
\`GET /projects/{id}/workspace\`, layer management, feature patching, and
feature-history endpoints. This is a local-first application, not an
authenticated multi-user collaboration product.

## Python/C++ separation

C++17 native kernels in \`geometry/native/editor.cpp\` handle:

- Nearest point-to-vertex and point-to-edge snapping in metric XY
- RDP path simplification for up to 20,000 points
- Detection of nonadjacent closed-ring segment crossings

They are compiled via CMake and exercised through both Release and Debug
CTest runs. C++ assertions remain enabled in Release tests.

The Python package in \`geometry/editing.py\` handles:

- WGS84 coordinate checks, projection into a local meter-based CRS
- PyProj geodesic circles, numerical azimuths and metric constructions
- Shapely polygon validation, holes, split and other overlays
- ctypes calls into native kernels with compatibility fallbacks

React + MapLibre handle per-frame pointer events and interactive previews
without sending every mousemove to FastAPI. The map and server both reject
editing operations targeting locked layers.

## Quality gates

GitHub Actions runs native C++ tests in Release and Debug configurations,
Python API and storage tests with the compiled C++ library enabled, TypeScript
type checking, Vite production build, and Vitest regression tests of editing
and undo/redo state.

This automated suite cannot prove the accuracy of imported imagery,
professional cadastral legality, or performance of a real GPU model. It also
does not replace manual browser pointer and touch-device acceptance tests.

## Technical references

- [Terra Draw / MapLibre editor reference](https://makewithmaplibre.com/plugins/terra-draw/)
- [Shapely split operation](https://shapely.readthedocs.io/en/stable/reference/shapely.split.html)
- [Shapely geometry overlays](https://shapely.readthedocs.io/en/latest/set_operations.html)
- [PyProj Geod](https://pyproj4.github.io/pyproj/stable/api/geod.html)


See also [Advanced GIS workflows](ADVANCED_GIS.md) for linked topology,
vector tracing, attribute tables, GDAL import/export, terrain analytics,
SAM 2 refinement and browser performance tests.


Layer labeling, editable map notes, categorized colors, legend, scale bar
and identify/inspection are covered by [Cartography guide](CARTOGRAPHY.md).
See [Multi-dimensional tests](TEST_MATRIX.md).
