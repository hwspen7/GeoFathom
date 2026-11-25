# Remote Sensing scientific computing

## Managed acquisition cubes

The workbench's **Multi-date optical cube** collects explicit UTC datetimes,
sensor identities, managed disk reflectance bands and per-acquisition QA.
The first retained acquisition supplies the target geometry. The background
`remote_cube` job builds 2–64 date, 1–12 role cubes with a full-resolution
band/time layout and one valid-observation-count band per role. Each source
is calibrated and QA-screened before its continuous reprojection. Missing
observations remain NoData. Cross-sensor inputs require an external
harmonization record; a declaration does not establish physical equivalence.

Execution uses verified input snapshots, the existing global raster lease,
isolated process budgets, cooperative cancellation and completed-only output.
Target grids support up to 150 million cells subject to explicit disk and
work budgets. The local CLI is `python -m imagery.remote_cube config.json cube.tif`;
its config uses target_path and acquisition bands/quality path bindings.
HTTP jobs accept opaque image IDs exclusively. A completed cube can be
registered as managed imagery and used for windowed trend/season/change-point
methods. UTC offsets become actual elapsed days, preserving the time origin
in the cube receipt. No regular acquisition interval or gap filling is assumed.

## Common-grid preparation and scene discovery

The workbench searches the approved public Sentinel-2 catalog by WGS84 region
and date range and filters the returned page by known scene cloud cover. This
is a bounded catalog page, not an exhaustive cloud-free scene search. Native
crop import also binds SCL as QA. The **Prepare aligned bands** action calibrates
each selected scientific band, decodes and nearest-aligns QA to that band's
native grid, screens native pixels, then resamples to the explicitly chosen
reference geometry. Categorical bands always use nearest neighbor. Cloudy
science values therefore cannot contaminate neighboring clear pixels through
bilinear interpolation. The prepared physical bands replace the active
bindings without applying calibration twice; per-band missingness is retained.

`POST /analysis/remote-sensing/prepare` accepts sources, bindings, declared
quantities, quality, target, target_quantity and nearest/bilinear resampling.
It returns GeoTIFF bands, a common-support mask and a deterministic receipt
with input/output hashes, physical calibration, QA order and per-band support.
It is bounded to 12 million decoded cells and 48 MB encoded output. This stage
does not infer atmospheric parameters, remove clouds by reconstruction, or
claim that different sensors have been radiometrically harmonized.

## Spatial validation partition correction

All spatial classifiers, nested SVM tuning and cloud probability/calibration
models use the same deterministic recursive spatial block partition. Blocks
are anchored to projected coordinates and assigned before reading class labels.
An optional one-block buffer excludes actual neighboring blocks, including
diagonals, around the held-out region. The same exclusion applies to inner
tuning/calibration partitions. This replaces the repeating modulo assignment,
whose one-block dilation excluded every training fold for 3–7 folds.

The mandatory gate includes an independent pairwise block-distance oracle for
3–10 folds and end-to-end buffered runs of all seven model families. Small
regions or sparse classes can still legitimately lack training support; they
fail explicitly rather than disabling the requested buffer. Spatial holdout
scores remain conditional on the region, block size and supplied labels and
do not establish external-site accuracy.

Remote Sensing is an independent workspace module, with typed HTTP catalog and execution endpoints, map preview, publication figure sources, CSV/GeoTIFF output, and SHA-256 provenance. It shares the spatial scientific product and Scientific Figure Studio contract without changing the Terrain or Spatial Analysis algorithms.

## Method scope

70 executable methods across nine groups: calibrated reflectance export and explicit reprojection, 20 optical spectral indices, three QA masks, six change and transition methods, three thermal methods, five radar methods, six temporal methods, PCA, spectral angle, native three-band true/false-color composites and fully constrained spectral unmixing, supervised classification and two validation methods. Role-to-band bindings are explicit, including multiple bands of a single GeoTIFF. Source data must be georeferenced and north-up; analysis requires exact alignment unless using the explicit continuous bilinear or categorical nearest-neighbor alignment operation. No implicit satellite sensor, band order, resampling or atmospheric correction is assumed.

Use already calibrated reflectance, native GeoTIFF scale/offset, explicit custom calibration, or Landsat Collection 2 SR/ST presets. Original Landsat DN zero is fill for the presets. Landsat 8/9 QA_PIXEL rejects bits 0–5; QA_RADSAT keeps zero flags. Sentinel-2 SCL conservatively retains 4, 5, 6 only. Binary quality masks retain one; masks can apply globally or to individual band roles, enabling per-date cloud screening. Sentinel processing-baseline offsets must come from the product metadata; do not assume that all L2A data use a zero offset. Calibrated reflectance is supported within [-0.2,1.6], outside [0,1] is reported, not clipped. Undefined ratios are NoData. User declarations do not certify actual radiometric or atmospheric accuracy.

- USGS Collection 2 surface reflectance: https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-reflectance
- USGS QA: https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands
- Copernicus Sentinel-2 L2A: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S2L2A.html

Thermal Planck and emissivity correction require sensor constants and do not constitute atmospheric LST retrieval. Radar inputs must already be radiometrically calibrated power or dB; dual-polarization RVI is a proxy. Legacy temporal methods operate on four aligned acquisitions; variable-series methods support 6–64 acquisitions; numeric time units are declared by the user. Classification uses explicit training labels and minimum spectral distance; agreement uses an independent reference raster supplied by the user, but independence and sampling design cannot be verified by software. Transition areas are planar projected cell areas. PCA uses a complete-case covariance basis; repeated eigenvalues can make components non-identifiable.

## Verification and limits

The remote scientific reference workflow requires independent numeric fixtures for every method, sensor calibration and QA tests, API failure/recovery, per-date masking, a 512x512 raster case, and actual remote-to-spatial-to-Figure-Studio pipelines. Missing or skipped mandatory evidence fails the gate. The browser tests use an actual small GeoTIFF. This is a bounded synchronous inline processor: 2 million cells per band, 8 million combined decoded cells, 48 MB base64 payload. Native sensor ingestion, STAC asset download, reprojection orchestration, atmospheric correction, SAR SLC/InSAR, deep learning, multi-scene streaming beyond the local optical path, and independent real satellite benchmarks are not included in this implementation. No arbitrary scientific maturity score is certified by synthetic fixtures.

The expanded methods include pre/post vegetation and burn indices (no empirical severity thresholds assumed), adaptive Lee-type speckle smoothing with specified ENL, Theil–Sen and classical OLS slope uncertainty, nonnegative sum-to-one spectral mixture fitting with labeled endmember means, and map-stratified area-adjusted accuracy with finite-population standard error under a declared stratified random sampling design. Each has a separately mandatory numerical oracle. The preprocessing methods allow explicitly resampling optical/QA grids, e.g. Sentinel-2 10 m and 20 m, but do not silently align an analysis request. QA must be applied after nearest-neighbor resampling, not bilinear interpolation.

True and false color preserve native three-channel float64 reflectance GeoTIFFs, role descriptions, common validity mask and independent projected PNG preview. The publication figure consumes all three scientific bands explicitly, without contrast stretching. Independent GDAL CLI alignment is mandatory in the remote reference workflow.

## Research depth extensions
The catalog now contains 66 methods. The 11 additions cover single-channel thermal radiative transfer inversion using supplied atmospheric quantities, C-correction with homogeneous calibration mask and Terrain angles, NDVI covariance-aware first-order uncertainty, Euclidean and stable-reference Mahalanobis change vectors, regularized equal-prior LDA with spatial block holdout, and 6–64 date composites/count/trend/harmonic analysis. Each uses explicit inputs and is included in the mandatory reference gate. No atmospheric profile estimation, IR-MAD, random forest, SVM, InSAR or scene-scale streaming is implied. The LDA validation is a specified holdout, not independent external-site validation; temporal fits use user-declared time units. Sources: https://www.mdpi.com/2072-4292/10/9/1450 and https://www.mdpi.com/2220-9964/6/9/287.

## Local disk-backed optical processing
The local CLI `python -m imagery.remote_windowed config.json result.tif --tile 512` processes the twenty pointwise optical indices in windows from aligned local GeoTIFFs, with global quality masks, full-resolution float64 export, streaming statistics, hashes, and no partial destination on failure. Config fields: `operation`, `bindings` (role to `path`, `band`, optional `encoding`/`scale`/`offset`), optional `parameters` and `quality`. It is intentionally not a path-reading HTTP endpoint. The inline workbench still has its original cell and payload caps. The mandatory integration fixture exceeds the inline per-band limit and checks every output pixel and late-failure cleanup.

SAR now also provides Gamma MAP intensity filtering, paired log-ratio change, and explicit flat-earth sigma0-to-gamma0 normalization (not radiometric terrain correction). Stable-reference canonical MAD returns the sum of standardized squared canonical alterations, rejects degenerate covariance and perfect canonical correlation, and does not claim IR-MAD or calibrated probability. Reference: https://www.isprs.org/proceedings/xxxi/congress/part2/164_XXXI-part2.pdf and https://ieeexplore.ieee.org/document/4060945/.

## Inference and correction extensions
77 catalog methods include conditional Lambertian atmospheric inversion (externally supplied path, transmission and spherical albedo), robust Huber cross-scene harmonization with disjoint calibration and reference pixels, iteratively reweighted MAD with effective sample size and convergence diagnostics, Euclidean cloud-buffer dilation, and exact single-mean-shift breakpoint time/jump/strength for variable date series. Nonconverged IR-MAD is explicitly diagnostic; breakpoint strength is descriptive, not a statistical significance test. These are not automated aerosol retrieval or general land-cover disturbance detection.

## Spatial classification cross-validation
80 catalog methods now include scikit-learn random forest, RBF SVM and shrinkage LDA, with all spatial folds evaluated, training-only preprocessing, fixed hyperparameters, optional block buffer, OOF confusion matrix, macro F1 and balanced accuracy. The final deployable classification refits all labels; its reported accuracy is explicitly out-of-fold, not in-sample. Dependencies are pinned in platform constraints. No automatic hyperparameter tuning or external validation is implied.

## Physical uncertainty, geometry and alignment
84 catalog methods include independent-input first-order uncertainty for single-channel LST (finite-difference reference test), angular volume-scattering SAR slope correction and local active layover/shadow validity (Vollrath, Mullissa & Reiche, 2020, https://doi.org/10.3390/rs12111867), and stable-mask normalized cross-correlation integer translation with overlap and ambiguous-peak rejection. These do not implement area-based RTC, passive shadow modeling, subpixel control-point registration or complete thermal model uncertainty.

## Wavelength-aware hyperspectral analysis
88 catalog methods include 6–64 wavelength-aligned reflectance bands, upper-envelope continuum removal, maximum absorption depth, sampled absorption center, integrated absorption area and deterministic successive-projection endmember candidates. Candidate spectra are not validated pure materials. The existing variable-axis API field `times` carries wavelengths in nm only for catalog methods declaring `axis: wavelength`; the workbench labels it accordingly.

Correlated LST uncertainty accepts all ten off-diagonal terms of a constant five-input correlation matrix, checks positive semidefiniteness and propagates per-pixel marginal standard deviations. Order: radiance, emissivity, transmittance, upwelling, downwelling. This is first-order conditional uncertainty, not structural model error or field validation.

Seasonal models now provide harmonic peak, onset, end and duration at a declared fraction of amplitude after detrending. Exact penalized dynamic programming provides multiple mean-shift count and first split time. Model phase is relative to the first acquisition; neither model phase nor penalized change points establish observed phenology or statistical significance.

Subpixel translation uses a fixed complete calibration support, bounded Powell optimization of normalized correlation, no wrapping, and optional held-out mask 2 radiometric RMSE. It does not establish geometric accuracy against independent ground control points or implement orthorectification.

Nested SVM selection evaluates a fixed three-C grid within each outer training partition, using only remaining spatial folds, with training-only scaling and optional block buffers. Outer labels cannot affect that fold's selection. Final map tunes and refits on all available labels; external validation remains separate.

SAR additions: explicit LUT amplitude gain/noise power calibration, wrapped interferometric phase and sample complex coherence from already coregistered SLC components. This is not full SAR mission focusing, terrain flattening, orbit correction, unwrapping, or displacement inversion. Spectral bright-cloud candidates use explicit visible whiteness and SWIR thresholds; they are not validated cloud truth or an autonomous operational cloud model.

## External and real-scene evidence
The independent real-scene workflow downloads two immutable published Sentinel-2 L2A subset bands (Zenodo DOI 10.5281/zenodo.21917533, tile T33UUP, 2023-09-07), verifies their published MD5 checksums, records SHA-256, and compares a native 512x512 difference computation against independently calculated NumPy reference pixels and masks. It does not infer undocumented reflectance calibration. External independently produced single-band reference rasters can be checked using `python scripts/remote_scene_reference.py --candidate actual.tif --reference reference.tif --atol 0.01 --output comparison.json`. Missing data/download failures are not a passing result. Actual satellite calibration, classification and ground-temperature accuracy still require independently labeled or measured reference data. New nested CV, seasonal and IR-MAD figure sources are rendered in the required synthetic gate.

Managed disk optical jobs integrate the twenty original optical kernels with the existing project job queue, global raster slot, process isolation, local operator permission, opaque image IDs, verified execution-time snapshots, progress/cancellation and completed-only GeoTIFF download. The workbench offers separate Add disk imagery and Run disk optical job controls. The bounded managed path accepts up to 25 million cells per band and 512 MB total snapshots; inline operations and nonpointwise algorithms retain their own limits. The new mandatory test covers managed snapshots, progress, output and cancellation cleanup; full UI and cross-process acceptance still require CI.

Cloud/shadow candidates now also support projected single-height solar geometry, dark-land screening, and a binary clear mask compatible with the existing quality-mask input. The optical cloud candidate and projected shadow methods are explicitly conditional heuristics, not validated operational cloud detection. The inline workbench remaps only selected in-memory sources, preventing unrelated disk-only sources from polluting inline requests.

## Analysis-ready STAC radiometry
The separate STAC NDVI extraction path now applies per-band raster-extension v1/v2 scale and offset or explicitly nonidentity native GeoTIFF calibration. Conflicting metadata and Earth Search already-applied-offset flags are rejected rather than guessed. The STAC path shares the conservative SCL 4/5/6 clear mask. The regression verifies a nonzero offset changes the actual classified area. See https://github.com/Element84/earth-search/blob/main/docs/collections/sentinel-2-l2a.md and https://github.com/stac-extensions/raster .

## Focused analysis-ready research extensions
110 methods include covariance-aware two-sensor generalized least squares fusion, its standard uncertainty and standardized discrepancy; conditional Beer-Lambert gap-derived LAI and PAR absorption proxy; and reproducible K-means plus standardized residual distance. The canopy models require independent gap fraction, extinction and clumping inputs and are not stand-alone optical LAI/FPAR product retrieval. Fusion requires aligned unbiased measurements of the same quantity and consistent units. Clusters are not land-cover truth. Each method has a mandatory mathematical reference test.

## Shared calibration and halo-aware disk science
Inline and disk calculations share a single calibrated-band reader with identical unit, range, DN, metadata and nodata validation. The catalog advertises a `windowed` capability per finite-neighborhood operator: optical indices, uncertainty, calibrated reflectance, selected change, physical thermal, SAR, quality, fusion and canopy operators. Lee, Gamma MAP and cloud buffering read their exact dependency halo and crop to the native tile, preserving scene-edge semantics. The managed job now accepts explicit units, Landsat ST encoding and role-specific masks. Seven mandatory seam tests compare two tile sizes against the whole-grid output. Global model fitting, nonlocal alignment and long time series are not yet tiled by this path.

The acceptance gate now requires all catalog-advertised disk methods to match their independently tested inline calculation, seven additional cross-seam comparisons, role-specific QA and calibration conflict rejection, and the STAC nonzero-offset regression. Spectral remote resampling uses float64 VRT output to avoid integer rounding before physical calibration. Missing or skipped evidence fails the gate. These are computational consistency tests, not independent field-accuracy estimates.

The published real-scene downloader uses the Zenodo record-file content API and the public record download endpoint as a transport fallback, preserving the same immutable file checksums. Network or validation failure produces an explicit `passed: false` JSON artifact and a nonzero exit status; no synthetic fallback or permissive acceptance is used. Cached or independently downloaded matching files can also be supplied in the fixture directory.

## Managed variable-axis disk cubes
The 14 variable-date methods and three local hyperspectral absorption methods also accept disk jobs with 6–64 ordered acquisition times or wavelengths, dynamic role binding and per-acquisition quality masks. The scheduler shrinks actual spatial windows to bound cube memory and quadratic change-point work. Temporal missingness is preserved rather than dropping every incomplete pixel. Global endmember extraction remains a whole-population method. Each local cube method has a mandatory tiled-versus-inline QA and missingness regression.

## Explicit product-band suggestions
The workbench recognizes official Landsat 8/9 Collection 2 Level-2 single-band filenames and Sentinel-2 tile/time/band/resolution filenames. Suggestions require one unique scene and one file per requested role, distinguish B08 and B8A, map QA_PIXEL/QA_RADSAT/SCL, and reject ambiguities. Users must review physical calibration and resolution; filenames alone do not establish Sentinel reflectance scale/offset or that exported Landsat values are original DN. No automatic cross-acquisition matching is performed. Sources: https://www.usgs.gov/faqs/how-do-i-use-a-scale-factor-landsat-level-2-science-products and Copernicus Sentinel-2 Product Specification.

## Resolution support and independent-reference diagnostics
Four methods add exact nested-grid area mean and valid support fraction (same projected metre CRS and integer-aligned native cells), paired continuous reference residual maps with bias/RMSE/MAE/NMAD/R²/correlation and coverage, and binary reference error maps with confusion matrix, F1, IoU, sensitivity and specificity. The last two accept user-supplied independently produced reference rasters but cannot establish that reference independence or real-world accuracy without the source observations. No resampled pixel is treated as additional independent measurement.

The generic quality dispatcher is restricted to its three QA-decoding methods, so spectral cloud and projected-shadow candidates reach their own kernels. This fixes the three KeyError failures recorded in the 103-method CI run. Reference-raster comparisons now stream 512-cell windows for full-scene RMSE, bias, tolerance and mask agreement; the new regression places a known error in the final window. Actual cluster and validation figures are included in the rendering gate. No reference download or new test pass is presumed.

## Native Sentinel-2 STAC crop import
The workbench can request a trusted Earth Search L2A item by ID, WGS84 bounds and selected spectral roles. The new local-operator endpoint returns calibrated, native-grid single-band GeoTIFF crops, up to 1024×1024 pixels per band and 24 MB combined; no arbitrary asset URL is accepted. Per-band calibration, window, transform and hash are returned. Mixed native resolutions require explicit alignment; the crop UI does not implicitly apply SCL or claim atmospheric retrieval. Landsat C2 L2 and Sentinel C1 L2A collections are supported by metadata search; Landsat requester-pays asset download is not implemented. Fixture regression mocks the approved public URL with a real GeoTIFF and checks calibration/native resolution, not internet availability.

## Spectral inference and physical-library inversion
120 methods include regularized global RX, noise-whitened MNF from adjacent differences, target/background spectral matched filtering, and discrete Bayesian LAI inversion from an externally supplied simulated or measured spectral library. The latter accepts explicit rows of LAI, prior mass, blue, green, red, NIR; independent per-band Gaussian error SDs, library fit threshold, posterior mean/SD and minimum chi-square diagnostics. The library hash is included in the receipt. A PROSAIL-generated library may be used, but PROSAIL forward simulation itself is not bundled. Global spectral fits are deliberately excluded from independent tile processing. All six methods have analytic or independent linear algebra reference tests.

## Advanced analysis-ready models
127 methods include dual-channel Hermitian covariance eigenvalue entropy/purity/minor power fraction with PSD validation, RossThick–LiSparse reciprocal c-factor correction using supplied BRDF coefficients, support-constrained local temporal transfer with exact native coarse-block mean conservation, and supervised three-class gradient-boosted cloud/shadow estimates with spatial OOF Brier score/log loss/confusion diagnostics. These are not quad-pol decomposition, automatic BRDF fitting, STARFM/ESTARFM, or Fmask/s2cloudless. References: https://rami-benchmark.jrc.ec.europa.eu/_www/definition.php and https://doi.org/10.3390/rs70607447. The cloud model requires independently meaningful labels and external validation before interpreting probabilities operationally.

## Anchored phase reconstruction
129 methods include coherence-weighted sparse least-squares phase-gradient reconstruction on the reference-connected component and conditional reference-relative radar range conversion. Disconnected components remain NoData; reference congruence, iteration budget, wrapped consistency and weighted gradient residuals are checked. Least-squares phase can be noncongruent around residues, so this is not a substitute for validated operational phase unwrapping or independently corrected interferometric deformation products. A synthetic multi-wrap plane with a disconnected region is the mandatory reference.

## Optional PROSAIL forward simulation
`scripts/build_prosail_library.py config.json library.csv` delegates actual PROSPECT-D/4SAIL SDR spectra to the established external `prosail==2.0.5` package in a compatible scientific Python environment (not a required application dependency). The JSON explicitly supplies sensor identity, four wavelength/response curves, and 2–2048 parameter samples with prior masses; the BOUNDS keys in the script specify the required sample schema. Integration uses measured spectral response over the 400–2500 nm spectrum, not nominal center wavelengths. Paste the headerless six-column library into the workbench's Bayesian LAI methods. The receipt records input and library hashes; the inversion receipt preserves the complete library. Mandatory tests verify response convolution and adapter arguments using an analytic stand-in; actual PROSAIL execution requires the external package and is not certified by that stand-in. Reference: https://pypi.org/project/prosail/2.0.5/ .

## Joint retrieval, two-anchor fusion and calibrated cloud inference
139 methods include correlated-error joint LAI/Cab finite-library posterior means, SDs, parameter correlation and effective hypotheses; bracketing reference-pair fusion with coarse support conservation and separate anchor disagreement; and spatially independent inner temperature calibration and outer probability evaluation. The optional PROSAIL script accepts --joint to retain Cab in the seven-column library. The posterior is conditional on the supplied library, anchor disagreement is not calibrated uncertainty, and cloud calibration is not external-site validation. Each method has an independent reference regression; advanced plots use actual posterior masses, held-out probability bins, ROC points and confusion counts.

Five specialized publication recipes are registered in the common figure studio (reliability with sample-size symbols, ROC, discrete joint posterior, marginal posterior, signed anchor quantiles). Each renders the actual supplied numerical evidence, preserves derived plot tables, and supports vector output through the shared renderer. The scientific gate checks actual results through PNG/SVG rendering, and the general gallery tests exercise PNG/SVG/PDF for every registered recipe. No visual interpolation of posterior masses is performed.

Additional mandatory regressions test nonidentifiable physical libraries (identical spectra must retain broad posterior uncertainty), nonzero two-anchor subpixel disagreement with exact coarse conservation, and Cab preservation through the optional PROSAIL adapter. The workbench requires both parameter axes to vary and checks the seven-column library width before submission.

## Satellite statistical change and arbitrary grid support

144 catalog outputs include a two-sided Gamma multilook intensity ratio F test and pointwise log-ratio confidence bounds with explicitly supplied before/after ENL. The three kernels are available in disk execution and do not infer ENL, calibration, temporal independence or multiplicity correction. Exact non-nested rectangular overlap uses sparse separable axis intersection matrices to remap intensive measurements and report valid-area support on shifted or non-integer-resolution grids in the same projected metre CRS. It is not an equal-area geodetic transformation or sharpening algorithm. Analytic reference and disk parity fixtures are mandatory.

## Local satellite geometry and full-scene conservative transfer

Run python -m imagery.satellite_geometry controls.json to fit a robust Huber affine mapping of explicitly paired pixel centers and projected ground control points. The independent checkpoint set is excluded from fitting, with axis RMSE, radial P95, bias, conditioning and convergence reported. The output affine follows the pixel-corner convention. It is local geometric calibration, not RPC-based orthorectification or an automatic image resampling service.

Run python -m imagery.remote_support_disk config.json output.tif for exact area support and coverage between non-nested native grids. The config supplies source_path, target_path, source_band, target_band, unit, mode, minimum_coverage and tile. The implementation reads only exact source support for each target window, respects masks, limits work, records input/output hashes, checks that source files did not change, and publishes only completed output without overwriting files. The two tile sizes and independent inline reference are mandatory tests. Currently local CLI only.

## Quality-weighted optical products and acquisition-network InSAR

147 catalog outputs add three explicit quality-weighted reflectance products (mean, observed spread, Kish effective support). Zero-weight or missing pairs are omitted, not imputed. They run both inline and windowed with matching semantics; quality weights are not inverse variance. The local CLI python -m imagery.insar_timeseries config.json output.tif performs conditional weighted inversion of an explicitly ordered graph of already corrected unwrapped-phase GeoTIFF bands, one band per acquisition pair. It anchors the first date, requires full rank for each pixel, reports relative LOS range and conditional SD for each later date plus residual chi-square and degrees of freedom, and masks disconnected pixel graphs. The JSON supplies input_path, times, pairs, sigma (radians), wavelength, range_sign and tile. This is a bounded acquisition-network inversion, not end-to-end SBAS/InSAR, does not model shared-acquisition covariance or atmospheric/orbit/topographic corrections. Independent weighted covariance, disconnected support and actual multiband disk output are mandatory tests.

## Radiometric uncertainty and cross-sensor spectral response

149 catalog products now include the local Lambertian inversion Jacobian norm and correlated first-order reflectance standard uncertainty for TOA reflectance, path reflectance, combined transmission and spherical albedo. The covariance model requires a positive-semidefinite supplied correlation matrix; a minimum inversion denominator masks unstable support. Both products share inline and disk kernels. The CLI python -m imagery.satellite_radiometry config.json integrates supplied spectral response and optional solar irradiance exactly for piecewise-linear curves on the union of spectral knots, supports batches of spectra, refuses unsupported nonzero response coverage, and records the input checksum. Neither feature automatically retrieves aerosol or water vapor or implements a complete 6S atmospheric simulator.

## RPC geometry and shared-acquisition InSAR covariance

The local CLI python -m imagery.satellite_rpc config.json output.tif maps target pixel centers through DEM heights and supplied RPC polynomial coefficients into native image coordinates. It samples a georeferenced DEM at the target grid, refuses an undeclared/non-ellipsoidal height reference, restricts normalized RPC support, supports nearest or strict bilinear image sampling, rejects missing support and limits native source windows. Config supplies input_path, dem_path, target_path, height_reference (WGS84_ellipsoid_m), source_band, dem_band, quantity, unit, resampling and tile. The output is an RPC/DEM-corrected raster with source and result hashes. It does not calibrate RPC bias, transform a geoid height datum, model occlusion or certify real-scene geolocation. The synthetic height-sensitive polynomial is tested independently.

InSAR inversion accepts optional epoch_sigma, a phase SD per acquisition. The pair covariance becomes diag(sigma^2) + B diag(epoch_sigma^2) B^T with the full signed acquisition incidence B. Each supported pixel uses its observed principal covariance submatrix, Cholesky whitening and rank-checked SVD. Conditional epoch uncertainty and weighted residuals are tested against an independent GLS formula. This does not remove actual atmospheric or orbit errors or estimate the covariance automatically.

## Native Landsat 8/9 Level-1 radiometry

The local CLI python -m imagery.landsat_level1 config.json output.tif consumes official Collection 2 Level-1 MTL.json metadata and the exact named original DN, QA_PIXEL and QA_RADSAT GeoTIFFs in its directory. It implements USGS gain/offset TOA radiance and solar-angle reflectance, and Planck at-sensor brightness temperature, with optional explicitly calibrated per-pixel solar elevation. It rejects all nonzero QA_RADSAT and QA_PIXEL bits 0–5; water is retained. It streams native 30 m product grids and hashes input/output files; panchromatic 15 m is intentionally excluded rather than silently remapping QA. Config: mtl_path, band, product (reflectance, radiance or brightness_temperature), tile, optional solar_elevation_path. This is not surface reflectance/temperature retrieval or Level-0 telemetry processing. USGS references: https://www.usgs.gov/landsat-missions/using-usgs-landsat-level-1-data-product and https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands .

## External atmospheric LUT and polarimetric change

151 catalog outputs include dual-pol complex Wishart covariance likelihood-ratio change statistics and asymptotic chi-square p-values. Singular/indefinite covariance is masked; supplied equivalent looks and independent covariance estimates are assumptions. Inline and tiled kernels share implementation. The local CLI python -m imagery.atmospheric_lut_disk config.json output.tif performs band-specific external LUT correction using aligned TOA, AOD and water-vapor rasters. It interpolates externally supplied path reflectance, combined transmission and spherical albedo on bounded AOD/water axes, masks extrapolation and unstable retrievals, requires matching water units, and hashes sources and output. The LUT model, reference wavelength, geometry and atmospheric profile must be established externally. This is not automatic aerosol retrieval or a bundled 6S engine. Config supplies toa_path, aod_path, water_path, lut_path, tile and minimum_denominator; the AOD raster is tagged aod and water raster uses the LUT's water_unit. Independent matrix likelihood and synthetic interpolation/disk tests are mandatory.

## Multi-track displacement decomposition

157 catalog products include local east/up InSAR displacement, component standard deviations, east/up error correlation and the geometry condition number. Each target cell has two LOS observations and uncertainties plus two local incidence and true-north sensor-facing azimuth angles. Observations must refer to the same interval and spatial reference and be positive toward the sensor. A north component and its independent uncertainty are explicitly prescribed, not estimated; the solver propagates correlated LOS error and the north uncertainty through the local 2x2 inverse. Poorly conditioned cells are excluded from displacement and uncertainty outputs; finite condition numbers remain available for diagnostics. Independent numerical matrix/covariance oracles and tiled parity are mandatory. These products do not establish full 3D displacement or correct atmospheric/orbit error.
