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

## Verification

Run python -m pytest tests/test_lidar_science.py tests/test_lidar_advanced.py -q. Tests cover analytical planes, degenerate neighborhoods, exact voxel counts, scaled LAS coordinates, partial overlap, directed distance, TIN interpolation, malformed input and HTTP contracts. These are synthetic reference tests, not real-flight validation.

## Remaining research work

LAZ/COPC/EPT and tiled streaming; embedded CRS and vertical-datum verification; classification and adaptive ground filtering; return/intensity metadata; global registration and independent checkpoints; full M3C2 with spatially varying and spatially correlated uncertainty; occlusion-aware density; canopy structure and segmentation; georeferenced raster and point-cloud exports; interactive large-cloud LOD and real-scene benchmark datasets. No publication-grade maturity score is asserted before numerical, performance, real-scene and end-to-end acceptance.
