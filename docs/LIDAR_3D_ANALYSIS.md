# 3D and LiDAR research workbench

This independent module starts from the integrated scientific figure baseline. It implements metric XYZ cloud processing; it is not a complete airborne laser-scanning production pipeline.

## Inputs and assumptions

- Uncompressed LAS 1.2–1.4 coordinate records and UTF-8 XYZ CSV (x,y,z columns); at most 100,000 points and 16 MiB per file. LAS scale and offset are applied. LAS CRS metadata and classification are not automatically interpreted. The operator assigns and confirms a common projected metre CRS and vertical datum; no reprojection or vertical-datum transformation is performed.
- Reference clouds must already be registered. Ground-normalized height requires separately identified ground points.
- No silent point sampling for analysis. Full numeric tables and SHA-256 provenance are exportable; figure inputs are limited to 10,000 evenly spaced result rows, disclosed in the receipt.

## Implemented scientific methods

Quality and exact duplicates; globally anchored voxel centroids and count conservation; local covariance eigenanalysis with degeneracy masking; spherical count density (no edge correction); observed vertical frequency; directed unsigned nearest-neighbor distance; paired-cell median elevation changes with common-support signed volume; TIN barycentric ground height with no extrapolation and a maximum triangle-edge constraint.

## Advanced methods

Trimmed rigid point-to-point ICP uses centered SVD, proper rotations, maximum correspondence distance and reports convergence and residuals. It is a local optimizer, not global registration. Robust statistical outliers use mean kNN distances, a median/MAD scale and an explicit zero-scale rule. M3C2-inspired normal projection uses baseline core voxels, local PCA normals and common cylinders, with conditional pointwise Welch intervals including operator-supplied registration standard uncertainty. These intervals are not corrected for spatial autocorrelation, normal uncertainty, or multiple testing. Canopy structure uses independently supplied ground TIN elevations and per-cell height percentiles; return fractions must not be interpreted as area cover or LAI.

## Geometry and structure extension

Local slope ground filtering uses locally supported lower-envelope seeds and TIN heights, with unsupported points kept unknown. A 2.5D TIN exports every triangle, 3D and projected area, and rejects long edges. Regularized 3D alpha-complex boundaries export consistently outward-oriented triangles and tetrahedral volume. Robust point-to-plane ICP uses Huber weights, SVD observability checks, and centered six-dimensional increments. Deterministic sequential RANSAC with orthogonal refinement extracts planar candidates; sparse CHM peak suppression extracts candidate crown apices. Neither candidate method constitutes validated semantic classification.

## Disk-backed and covariance extensions

Install the optional LiDAR extension with python -m pip install -e ".[lidar]". LAZ decoding uses laspy/lazrs. The streaming LAS/LAZ operation processes up to 10 million records in 100,000-point chunks, accumulates additive statistics in a temporary SQLite store, and rejects outputs above 100,000 occupied voxels. Counts, centroid coordinates, elevation extrema, classification and return-number counts are preserved. It validates embedded horizontal CRS when present; it does not transform vertical datums. The 512 MiB upload cap and bounded output are explicit. This is not an out-of-core implementation of all algorithms, nor a spatial-indexed COPC reader.

The common-cell change operation estimates conditional volume uncertainty by combining within-cell mean sampling variances with an operator-specified exponential spatial covariance of registration error. All pairs are evaluated in bounded memory blocks. No empirical variogram calibration or autocorrelation adjustment to within-cell sampling error is claimed.

## Progressive morphology and registration

The PMF operation uses bounded multiscale grayscale openings and a progressive slope-related tolerance. Its nearest-filled intermediate surface is not an observed DEM; final ground estimates use supported TIN interpolation. Coarse PCA orientation initialization evaluates all 24 proper axis permutations and reports the best and second scores, but does not guarantee arbitrary partial-overlap alignment. GICP uses source and reference neighborhood covariances, positive noise floors, rotating covariances, whitened rigid least squares and six-dimensional rank validation.

For real-scene validation, acquire a classified LAS/LAZ tile from USGS 3DEP (https://www.usgs.gov/the-national-map-data-delivery/gis-data-download). Run scripts/lidar_scene_reference.py with an explicit metre EPSG, projected bounding box and output JSON. The script reports confusion matrices, coverage and F1 against existing LAS labels; those labels are not independent survey truth. The operator must select the crop before evaluation. No real-scene result is asserted by the code alone.

## Verification

Run python -m pytest tests/test_lidar_science.py tests/test_lidar_advanced.py tests/test_lidar_geometry.py tests/test_lidar_disk_uncertainty.py tests/test_lidar_registration.py -q. Tests cover analytical planes, degenerate neighborhoods, exact voxel counts, scaled LAS coordinates, partial overlap, directed distance, TIN interpolation, malformed input and HTTP contracts. These are synthetic reference tests, not real-flight validation.

## Remaining research work

LAZ/COPC/EPT and tiled streaming; embedded CRS and vertical-datum verification; classification and adaptive ground filtering; return/intensity metadata; global registration and independent checkpoints; full M3C2 with spatially varying and spatially correlated uncertainty; occlusion-aware density; canopy structure and segmentation; georeferenced raster and point-cloud exports; large-cloud LOD beyond the included bounded orthographic preview and real-scene benchmark datasets. No publication-grade maturity score is asserted before numerical, performance, real-scene and end-to-end acceptance.
