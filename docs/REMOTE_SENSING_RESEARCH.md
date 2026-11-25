# Remote sensing research product upgrade

Development branch: `feature/remote-sensing-research`, initially based on the
shared `research-core`/`main` snapshot `e06eddb`. Each completed capability is
validated and published as a separate forward commit. No shared history is
rewritten.

| Priority | Delivered capability | Required evidence |
| --- | --- | --- |
| Scientific correctness | Shared contiguous spatial folds and actual geographic buffers across seven model families | Independent block-distance oracle, buffered model runs and spatial leakage checks |
| Preparation | Catalog date/region discovery, native SCL binding, physical calibration, native QA screening before common-grid reprojection | Cloud contamination, categorical nearest-neighbor, nonoverlap and actual browser NDVI workflow |
| Multi-date data | Managed windowed optical cubes, explicit UTC times, per-date missingness and valid counts; reuse by disk time-series analysis | Two tile sizes, known slope with missing dates, snapshot/cancellation, real process-isolated job and managed registration |
| Classification | Saved numeric random forests, spatial OOF evaluation, full-resolution deployment and descriptive probability/entropy/domain diagnostics | Independent scikit-learn equivalence, tile-invariant training artifact, project isolation and late-cancellation cleanup |
| Reference inference | Independent-reference error maps, training-location exclusion, probability diagnostics and spatial-cluster intervals | Independent confusion matrix and bootstrap oracle; PNG/SVG rendering from actual metrics |
| Reproducibility | Verified execution receipts, exportable recipes, checked repeats and explicit algorithm-version changes | Exact repeated raster hash; input-change rejection before and after scheduling; isolated worker replay |

## Scientific acceptance scope

The remote scientific workflow runs the numerical suites, a fail-closed required
evidence gate, frontend build/unit tests and the actual browser preprocessing
workflow. Its synthetic and computational consistency evidence does not certify
field accuracy. The separate published real-scene reference workflow retains its
original, explicitly limited native-arithmetic scope.

Saved-classifier validation supports independently supplied annotations and
reports their source and spatial separation. Real multi-site/season model
accuracy must be measured with appropriate independent observations. Users
cannot obtain a scientific maturity score merely from the number of catalog
outputs or passing synthetic fixtures.

## Remaining specialized scope

These changes establish a bounded common research workflow. They do not claim
automatic aerosol/water-vapor retrieval, operational pretrained cloud detection,
deep-network training/fine-tuning, complete native SAR mission/SBAS processing,
or calibrated structural uncertainty for every physical retrieval. Existing SAR,
thermal and hyperspectral operators retain their documented input assumptions.
Those domain extensions require their own scientific method and independent
reference datasets; they must not be represented by placeholder results.
