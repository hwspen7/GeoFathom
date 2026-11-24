# Spatiotemporal science

Independent workbench for 6–64 explicitly dated, aligned GeoTIFF bands or scenes. The numerical cube is capped at four million dated cells and 48 MB encoded input, with tighter per-model work limits. Metadata/custom/Landsat physical calibration shares the remote-sensing reader; optional QA applies globally or per date. No automatic resampling or implicit missing-date compression. Calendar dates are UTC day offsets with a recorded origin.

## Methods (37)
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
Run python -m pytest -q tests/test_spacetime_science.py . Every catalog method has a reference case, and explicit tests cover irregular dates, calibration, QA, alignment, independent batch Gaussian prediction and future-data isolation. Figure tests render actual result data to PNG and SVG. This is not proof of completed execution. Large disk-backed new-model computation, spatiotemporal kriging, spatial panel regression, external validation, and persistent cube storage remain outside this implementation.
