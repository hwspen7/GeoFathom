# Layer labels, annotations and categorized map styling

GeoFathom now supports standard cartographic workflows drawn from QGIS,
ArcGIS Pro and MapLibre GL JS. It is an initial practical subset, not
Maplex, QGIS PAL labeling, or an advanced print layout engine.

## Automatic labels from attributes

1. Create/open a project. In **Projects & saved geometry**, select a layer.
2. Expand **Labeling & map symbology**.
3. Enable **Automatically label visible features**.
4. Choose **Label source field**. Suggested values:
   - \`name\`: saved feature name
   - \`source\`: source attribution
   - \`@area_m2\`: authoritative WGS84 polygon area (m²)
   - \`@length_m\`: WGS84 line length or polygon perimeter (m)
   - Any stored attribute field name, such as \`category\` or \`landuse\`.
5. Adjust font size (9–28 px), text/halo color, halo width (at most ¼
   font size), minimum/maximum map zoom, and label overlap. Defaults
   avoid collisions, which may omit some labels on crowded maps.
6. Change polygon fill opacity or line width per layer. Label and symbol
   settings are stored in project-scoped SQLite with optimistic revisions,
   not in browser local storage.

A default layer has automatic labels **off** to avoid overwhelming the map.
Turning a layer off also hides that layer's automatic labels and notes.

## Independent map notes

Enter a brief message in **Map note / label text**, click **Place map note**,
then click the geographic point on the map. The note is stored as an
ordinary GeoJSON Point with \`annotation=true\` and \`annotation_text\`
properties. Notes display even when automatic labels are off.
They have the same permissions and version history as other saved features.

Open a note from the project feature list to edit its text, move it with
**Survey & geometry editor → Move**, restore a previous revision, or delete
it. Note text is plain, bounded text, never interpreted as HTML or JS.

## Categorized symbology / unique values

Select **Category color attribute**, such as \`landuse\`, then choose
**Generate colors for attribute categories**. Each of up to 20 distinct
values gets a deterministic class color. Missing or unknown values retain
the layer's normal color. You may edit a class's color individually.
The map legend shows visible classes for the saved project features.

This is the "unique values" / categorized renderer common in ArcGIS Pro
and QGIS. The advanced cartography panel additionally provides graduated
numeric ramps, conditional label predicates, and per-feature dragged label
offsets. Arbitrary expression-based styling, multi-field category definitions,
and full cross-layer label deconfliction are not yet supported.

## Map inspection, legend and scale

- **Map legend:** lists visible layers and categorized class colors; toggle
  with **Legend**. Hidden layers do not show.
- **MapLibre symbol labels:** geometry-aware text placement and collision
  handling for points, lines and polygons with text halos.
- **Scale bar:** interactive metric scale shown at lower left.
- **Coordinates:** mouse cursor longitude and latitude in WGS84, six decimals.
- **Identify feature:** select a saved geometry to inspect its name, type,
  source, attributes, measured area/distance and revision; zoom to it or
  copy its GeoJSON.

MapLibre uses a configurable glyph source for labels:
\`VITE_GLYPHS_URL\` (default MapLibre's public demo glyph server). For
fully offline use, supply local fonts/glyphs and your own raster tile
provider. Internet access is required for the default OpenStreetMap tiles.

## API and safety

- \`PATCH /projects/{project_id}/layers/{layer_id}/style\` accepts subsets of
  \`labels\` or \`symbol\` with optional \`expected_revision\`.
- \`POST /projects/{project_id}/annotations\` accepts a 120-character
  printable note, WGS84 coordinate pair and optional destination layer.
- \`GET /projects/{project_id}/workspace\` embeds each layer's validated
  style and revision.
- Layer visibility, labels, notes, colors and category palettes are project
  scoped. A project cannot update another project's layer.
- Category palette: at most 20 colors, named by category string.
- String fields, finite numeric ranges, colors, and zoom limits are checked
  server-side to prevent invalid map styles.
- Polygon area/line lengths are measured by Python/PyProj on the ellipsoid,
  not estimated by screen pixels.
- MapLibre receives bounded plain-text labels, not JavaScript expressions
  or HTML generated from arbitrary attributes.

The GeoJSON feature export retains notes and properties, but cartographic
layer styles are stored with the project and are **not embedded in ordinary
GeoJSON**. A future project-package exporter can preserve both.
