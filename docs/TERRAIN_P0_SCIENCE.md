# P0 — Independent scientific reference acceptance

The independent test gate deliberately runs a **separate GDAL gdaldem binary**,
rather than calling GeoFathom's own derivative implementation to generate its
expected answers. It records versioned reference-tool identity, valid cell count,
maximum absolute error, RMSE, p95 error and the enforced acceptance threshold.
The selected 10 m projected GeoTIFF has exact known synthetic topography.

| Comparison | Independent method | Max allowable disagreement |
| --- | --- | --- |
| Slope, Horn | GDAL gdaldem slope -alg Horn | 0.003 degree |
| Slope, Zevenbergen–Thorne | GDAL gdaldem slope -alg ZevenbergenThorne | 0.003 degree |
| Aspect, Horn | GDAL gdaldem aspect -alg Horn | 0.025 degree circular difference |
| Aspect, Zevenbergen–Thorne | GDAL gdaldem aspect -alg ZevenbergenThorne | 0.025 degree circular difference |
| TRI | GDAL gdaldem TRI -alg Riley | 0.001 m |
| TPI | GDAL gdaldem TPI | 0.001 m |
| Hillshade (single direction) | GDAL gdaldem hillshade | 4/255 brightness units |

The tool must not silently skip missing independent dependencies. Any compared
pixel with inconsistent NoData classification fails. Every comparison and
its actual error is stored in a JSON CI artifact.

**Important:** This gate proves agreement for seven synthetic numerical
configurations across five operations. It does not prove the scientific accuracy
of an arbitrary field DEM, establish correctness for the other 23 operations,
or replace independent hydrologic, visibility, engineering or 3D benchmarks.
No 95/100 certification is assigned without a complete evidence dossier.

The separate GitHub Actions workflow is
[Terrain scientific reference gate](../.github/workflows/terrain-science.yml).
To run locally on a machine with gdaldem available:

    python benchmarks/terrain_reference.py --strict --output build/terrain-reference.json


## Projection-scale numerical integrity

Meter-valued projected coordinates alone do **not** guarantee that cell
resolution corresponds to ground distance. The P0 preflight audits meridional
and parallel projection-scale factors at the center and four corners of each
DEM. A sampled scale error above **2.0% fails closed** with an actionable
request to reproject to a locally suitable metric CRS. Scale error above
0.5% (within the accepted 2% maximum) is also surfaced as a quality flag;
the actual sampled maximum is in the machine-readable result and UI.
Neither this geometric scale check nor a matching vertical datum label
validates the absolute survey accuracy of the elevations.
