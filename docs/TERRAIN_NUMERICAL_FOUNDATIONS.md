# Numerical foundations — Independent scientific reference acceptance

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
resolution corresponds to ground distance. The foundation preflight audits meridional
and parallel projection-scale factors at the center and four corners of each
DEM. A sampled scale error above **2.0% fails closed** with an actionable
request to reproject to a locally suitable metric CRS. Scale error above
0.5% (within the accepted 2% maximum) is also surfaced as a quality flag;
the actual sampled maximum is in the machine-readable result and UI.
Neither this geometric scale check nor a matching vertical datum label
validates the absolute survey accuracy of the elevations.

## Strict >=95 foundation controlled-numerical acceptance

The foundation gate includes **two independent known-answer scenes for each of the
28 operations**: a UTM linear-gradient plane and a horizontal zero-gradient
surface. Reference values are derived by algebra and explicit graph/geometry
identities, never by calling GeoFathom to generate expected answers. A
duplicate terminal cross-section near an interval multiple was corrected.

Run: `python scripts/terrain_numerical_gate.py --junit build/terrain-foundation-tests.xml --reference build/terrain-reference.json --output build/terrain-foundation-matrix.json`

| Evidence enforced by CI | Score |
| --- | ---: |
| Per-operation analytical plane reference | 45 |
| Per-operation zero-relief reference | 35 |
| All seven independent GDAL comparisons | 10 |
| Common scientific and projection-safety invariants | 10 |
| **Maximum** | **100** |

If one analytical scene fails, its operation scores at most 65 or 55;
if GDAL or any mandatory invariant fails, every operation scores <=90.
The gate requires **28/28 individually >=95**, not a passing average.
Evidence is emitted as a per-operation JSON matrix. It is deliberately
possible to fail the gate: there are unit tests for missing cases, missing
invariants and failed independent references.

**Scope:** The reported number is a controlled *implementation conformance*
benchmark score, not a measured probability of accuracy on an arbitrary
real DEM, not a guarantee of valid vertical datum, and not an external
field-survey certification. Independently surveyed ground control, realistic
data uncertainty and real-world vertical alignment remain outside this
benchmark. Running a reference gate must not falsely set a particular
user dataset's quality.reference_validation to independently certified.
