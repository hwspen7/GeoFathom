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
| QA support correction | Apply native QA before physical-value validation across inline, disk, preparation, cube and model paths | Extreme excluded first-pixel oracle in all five paths; same value rejected without its QA exclusion |

## Scientific acceptance scope

The remote scientific workflow runs the numerical suites, a fail-closed required
evidence gate, frontend build/unit tests and the actual browser preprocessing
workflow. Its synthetic and computational consistency evidence does not certify
field accuracy. The separate real-scene workflow now also checks a pinned human-labeled OSCD
transfer subset and a six-date metadata-calibrated L2A/SCL/cube/trend pipeline.
Native arithmetic, real processing consistency and annotation accuracy are
reported separately.

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

## Deepening batches

| Batch | Delivered | Evidence |
| --- | --- | --- |
| Physical and temporal semantics | Independent optical, SAR, terrain and LiDAR feature editor; UTC acquisition tags, time origin and slope units survive cube reuse | Mixed-unit models and conflicting-unit rejection; exact day/hour trend conversion |
| Harmonization | Provenanced per-role gain/offset and Ross–Li normalization; exact area support; bounded fit/check-mask registration gates | Independent area arithmetic, kernel-ratio correction and one-pixel shift rejection |
| Model trust | Nested spatial temperature calibration; standardized support distance; abstention and reference coverage/accuracy plots | Independent likelihood search, physical-unit invariance, portable calibrated inference and reference thresholds |
| Samples | Immutable project sample revisions, codebook, annotation reviewer/source/status, fixed training/reference roles and preflight | Overlap/buffer rejection, QA/class/fold support, generated labels used by actual training, reference-only training rejection |
| Experiments | Same-support parameter scans and feature ablations, spatial label-prior baseline, comparison figures and portable verified archives | Exact common sample identities, archive model replay, corruption/traversal rejection, cancellation and isolated managed replay |
| Actual data and scale | Public OSCD annotations, six-date real L2A processing and 4096×4096 resource/arithmetic benchmark | [Observed evidence and exact scope](benchmarks/README.md) |

Local scientific acceptance after these batches: 329 tests, 157 catalog method
oracles and 168 mandatory workflow checks passed. Frontend: 325 Vitest tests and
3 revision tests passed; production build passed. These counts describe checks,
not a percentage of real-world scientific accuracy. Remote CI independently
runs build, browser, scientific and real-data workflows on the published head.
