# Spatiotemporal science

Independent workbench for 6–64 explicitly dated, aligned GeoTIFF bands or scenes. The numerical cube is capped at four million dated cells and 48 MB encoded input, with tighter per-model work limits. Metadata/custom/Landsat physical calibration shares the remote-sensing reader; optional QA applies globally or per date. No automatic resampling or implicit missing-date compression. Calendar dates are UTC day offsets with a recorded origin.

## Methods (60)
- Cube coverage, observed exceedance, lag correlation, median/count and actual-time OLS and Sen trends.
- Tie-corrected asymptotic Mann–Kendall and BY adjustment; MK assumes temporal independence.
- Circular residual block-bootstrap slopes with shared resample indices, BY adjustment; approximate inference for complete regular series with stationary residuals.
- Harmonic amplitude, residual error, peak/start/end/duration; exact penalized segmentation and single mean-shift models reuse the remote-sensing scientific kernels.
- Expanding-window linear prediction, prediction SD, hindcast RMSE and persistence skill.
- Continuous-time integrated Brownian velocity state-space level/rate, future observation prediction/SD and prequential RMSE/skill; supplied variances, no automatic parameter tuning.
- Directional empirical space-time semivariance, acquisition-order lagged spatial association and conditional spatial exchangeability randomization with BY adjustment. Randomization does not test independence between autocorrelated fields.
- Complete-case EOF spatial mode, reconstruction RMSE and local reconstruction skill with global explained spectrum and principal-component time series.

## Products
Independent map layer, native GeoTIFF, CSV, source/calibration/QA/time/provenance receipt and shared publication figures: observed coverage, median with interquartile range, hindcast comparison, normalized innovation, directional semivariance, EOF spectrum and temporal scores. IQR is observed spatial spread, not a confidence interval. Forecast SD is conditional on the specified model. Space-time semivariances do not fit a predictive covariance model.

## Acceptance
Run python -m pytest -q tests/test_spacetime_science.py . Every catalog method has a reference case, and explicit tests cover irregular dates, calibration, QA, alignment, independent batch Gaussian prediction and future-data isolation. Figure tests render actual result data to PNG and SVG. This is not proof of completed execution. Large disk-backed model computation, external validation, persistent cube storage, nonseparable covariance, and geographically and temporally weighted regression remain outside this implementation.

The isolated local checks verified the five EOF/bootstrap methods, independent batch Gaussian forecast mean and SD, future observation isolation, and reproducible conditional spatial randomization using byte-identical algorithm modules with a minimal error-check stub. These nine checks are not application or browser acceptance. The dedicated workflow uses the existing locked scientific environment and a strict JUnit per-method gate; the Playwright spec exercises a real six-band GeoTIFF, slope export and map preview.


## Joint statistical models
- Ordinary space-time kriging: separable exponential covariance, nugget, profiled sill, optional bounded REML. Prediction includes observation nugget and mean estimation, not parameter-estimation uncertainty. At most 256 sampled training observations; conditional small-area research model, not large-scene kriging. Joint holdout excludes final dates and a contiguous spatial block (optional buffer) before sampling or fitting.
- Two-way fixed effects with one aligned time-varying covariate, balanced complete-case panel, CR1 spatial block clustered uncertainty. Cluster independence is an assumption, not established by block assignment. Covariate QA must be applied before import. No causal inference claim.
- Local Gi* and trajectory-permutation maximum statistic correction; only under exchangeability of complete spatial trajectories. Persistence classes are explicitly defined and not the ArcGIS implementation.
- Seasonal structural break scan compares full intercept/trend/harmonic fits with a BIC complexity penalty and at least one cycle on both sides. Not BFAST/CCDC/LandTrendr. Observed extreme runs split at missing dates and excessive gaps; observed interval spans are not continuous event durations.
- Figures now include directional lag-specific curves, actual semivariance heatmaps, categorical maps, panel residual/fixed-effect diagnostics, hotspot histories and joint holdout calibration summaries.

Local verification in isolation: exact Git blobs for spacetime_kriging.py (02b1713ec66526851e5ac7fa816e68fa89038312) and spacetime_panel.py (e1df880aa943ee91dc659972bb55d60237f39cdd) were executed with a minimal require stub. Dense augmented-matrix kriging mean and SD differed by at most 1.11e-16; the test REML objective decreased from 2.9081589 to 2.5168278. Joint holdout training was unchanged when excluded observations changed. Panel coefficients and residuals matched full dummy-variable least squares. The browser TIFF was independently generated and read back using Rasterio. Full application, figure and browser regression remain unverified until CI or a local checkout runs them.
