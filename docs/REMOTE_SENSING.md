# Remote Sensing scientific computing

Remote Sensing is an independent workspace module, with typed HTTP catalog and execution endpoints, map preview, publication figure sources, CSV/GeoTIFF output, and SHA-256 provenance. It shares the spatial scientific product and Scientific Figure Studio contract without changing the Terrain or Spatial Analysis algorithms.

## Method scope

42 executable methods across eight groups: 20 optical spectral indices, three QA masks, four change and transition methods, three thermal methods, four radar methods, four temporal methods, PCA and spectral angle, and supervised classification plus reference agreement. Role-to-band bindings are explicit, including multiple bands of a single GeoTIFF. Source data must be georeferenced, north-up, and exactly aligned; alignment is an explicit separate Spatial Analysis operation. No implicit satellite sensor, band order, resampling or atmospheric correction is assumed.

Use already calibrated reflectance, native GeoTIFF scale/offset, explicit custom calibration, or Landsat Collection 2 SR/ST presets. Original Landsat DN zero is fill for the presets. Landsat 8/9 QA_PIXEL rejects bits 0–5; QA_RADSAT keeps zero flags. Sentinel-2 SCL conservatively retains 4, 5, 6 only. Binary quality masks retain one; masks can apply globally or to individual band roles, enabling per-date cloud screening. Sentinel processing-baseline offsets must come from the product metadata; do not assume that all L2A data use a zero offset. Calibrated reflectance is supported within [-0.2,1.6], outside [0,1] is reported, not clipped. Undefined ratios are NoData. User declarations do not certify actual radiometric or atmospheric accuracy.

- USGS Collection 2 surface reflectance: https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-reflectance
- USGS QA: https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands
- Copernicus Sentinel-2 L2A: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S2L2A.html

Thermal Planck and emissivity correction require sensor constants and do not constitute atmospheric LST retrieval. Radar inputs must already be radiometrically calibrated power or dB; dual-polarization RVI is a proxy. Temporal methods operate on four supplied aligned acquisitions; numeric time units are declared by the user. Classification uses explicit training labels and minimum spectral distance; agreement uses an independent reference raster supplied by the user, but independence and sampling design cannot be verified by software. Transition areas are planar projected cell areas. PCA uses a complete-case covariance basis; repeated eigenvalues can make components non-identifiable.

## Verification and limits

The remote scientific reference workflow requires independent numeric fixtures for every method, sensor calibration and QA tests, API failure/recovery, per-date masking, a 512x512 raster case, and actual remote-to-spatial-to-Figure-Studio pipelines. Missing or skipped mandatory evidence fails the gate. The browser tests use an actual small GeoTIFF. This is a bounded synchronous inline processor: 2 million cells per band, 8 million combined decoded cells, 48 MB base64 payload. Native sensor ingestion, STAC asset download, reprojection orchestration, atmospheric correction, SAR SLC/InSAR, deep learning, multi-scene streaming, and independent real satellite benchmarks are not included in this implementation. No arbitrary scientific maturity score is certified by synthetic fixtures.
