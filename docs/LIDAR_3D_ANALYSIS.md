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

## Reconstruction and scientific exports

Progressive TIN densification admits lower-envelope candidates using current supported TIN height residuals, not all classic adaptive angle criteria. Uniform-grid Poisson uses centroid-oriented local normals, trilinear splats, a padded FFT Poisson solve and marching cubes for approximately star-shaped closed surfaces. It is not adaptive octree or screened reconstruction. It reports boundary and nonmanifold edges. TIN, alpha and Poisson export indexed OBJ; common-cell change and canopy p95 export CRS-aware GeoTIFF with unobserved cells as NaN, bounded to two million cells.

## Feature matching and spatial inference

Reciprocal k-nearest-distance descriptor matching and bounded RANSAC provide a partial-overlap initializer under comparable sampling density. Registration quality includes independently computed forward and reverse nearest-distance overlap. The cluster-aware normal change operation uses tangent-plane blocks, return-weighted cluster sandwich variance, conservative conditional t intervals and Benjamini–Yekutieli adjusted p values. Blocks are assumed independent; the method does not estimate full measurement covariance or normal uncertainty. Zero-variance tests are withheld. Sparse CHM marker watershed identifies true regional maxima, collapses connected equal-height plateaus, applies suppression independently within observed connected components, then uses a maximum-bottleneck graph flood without filling missing cells. Occupied footprint is not full crown area. Multiscale covariance geometry selects an identifiable neighborhood via normalized eigenentropy, a heuristic rather than validated optimal scale.

## Terrain and structural metrics

The cloth-inspired filter is a bounded inverted obstacle-constrained membrane relaxation, with a reported convergence flag. Canopy vertical complexity reports observed return-height Shannon entropy, effective layers, and occupied voxel volume. Planar roof candidates combine ground-normalized heights, local covariance geometry, connected occupied cells, grid perimeter, compactness and a height-volume proxy. Neither physical leaf area density nor semantic buildings nor enclosed volume can be recovered from these metrics alone.

## Screened reconstruction and anisotropic change

Screened uniform-grid Poisson augments the periodic discrete Laplacian with trilinear point evaluation S and the constraint penalty lambda times squared residual. A preconditioned conjugate-gradient solver reports residual, convergence and before/after sample errors. The bounded implementation is not octree Screened Poisson. Anisotropic covariance change propagates a horizontal/vertical measurement covariance floor, local Gaussian PCA eigenvector perturbation and independent registration variance into conditional change intervals and BY-adjusted probabilities. It does not model cross-covariance or spatial correlation of individual returns.

## Exact tiled neighborhood density

A disk-backed SQLite tile index streams LAS/LAZ records and evaluates all spherical neighborhoods with a complete 27-tile halo when tile width is at least radius. Each core point contributes exactly once and coincident returns are preserved. Output includes tile-wise count, mean/minimum/maximum neighbors, density and directed pair totals; no per-point export or survey-boundary correction. Explicit point, tile, halo and work budgets guard dense scenes. This is not a COPC octree query or EPT reader.

## Verification

Run python -m pytest tests/test_lidar_science.py tests/test_lidar_advanced.py tests/test_lidar_geometry.py tests/test_lidar_disk_uncertainty.py tests/test_lidar_registration.py tests/test_lidar_reconstruction.py tests/test_lidar_inference.py tests/test_lidar_structures.py tests/test_lidar_covariance_screen.py tests/test_lidar_tiles.py -q. Tests cover analytical planes, degenerate neighborhoods, exact voxel counts, scaled LAS coordinates, partial overlap, directed distance, TIN interpolation, malformed input and HTTP contracts. These are synthetic reference tests, not real-flight validation.

## Remaining research work

LAZ/COPC/EPT and tiled streaming; embedded CRS and vertical-datum verification; classification and adaptive ground filtering; return/intensity metadata; global registration and independent checkpoints; full M3C2 with spatially varying and spatially correlated uncertainty; occlusion-aware density; canopy structure and segmentation; georeferenced raster and point-cloud exports; large-cloud LOD beyond the included bounded orthographic preview and real-scene benchmark datasets. No publication-grade maturity score is asserted before numerical, performance, real-scene and end-to-end acceptance.
