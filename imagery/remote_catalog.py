"""Remote sensing scientific methods and explicit input semantics."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Method:
    id:str
    group:str
    title:str
    roles:tuple
    parameters:tuple
    unit:str
    assumption:str

# Role tuples are (semantic name, required physical quantity).
def refl(*names):return tuple((name,'reflectance') for name in names)
def numeric(*names):return tuple((name,'numeric') for name in names)
def p(name,label,default,minimum,maximum,integer=False):return (name,label,default,minimum,maximum,integer)
def m(id,group,title,roles,unit,assumption,parameters=()):
    return Method(id,group,title,roles,parameters,unit,assumption)

OPT='Calibrated comparable reflectance; no atmospheric correction or implicit band alignment.'
T=p('threshold','Change threshold',.1,0,1e100)
TIME=(p('time1','First acquisition time',0,-1e6,1e6),p('time2','Second acquisition time',1,-1e6,1e6),p('time3','Third acquisition time',2,-1e6,1e6),p('time4','Fourth acquisition time',3,-1e6,1e6))
TIMES=numeric('date1','date2','date3','date4')
CLASSES=(('before','class'),('after','class'))
SPECTRUM=refl('blue','green','red','nir')
SERIES_IDS={'series_median','series_count','series_slope','series_amplitude','series_harmonic_rmse','series_break_time','series_break_jump','series_break_strength'}
CV=(p('block_m','Block width (m)',100,1,100000),p('folds','Spatial fold count',5,3,10,True),p('buffer_blocks','Training exclusion buffer (blocks)',0,0,1,True))
METHODS=(
m('spatial_rf_cv','Classification','Random forest with spatial cross-validation',SPECTRUM+(('training','class'),),'class','Fixed hyperparameters, every labeled pixel held out once, final map refit; no external accuracy claim.',CV+(p('trees','Number of trees',64,16,256,True),p('max_depth','Maximum tree depth',12,2,30,True),p('min_leaf','Minimum leaf samples',2,1,30,True),p('seed','Random seed',42,0,2147483647,True))),
m('spatial_svm_cv','Classification','RBF SVM with spatial cross-validation',SPECTRUM+(('training','class'),),'class','Training-only scaling in every spatial fold, fixed hyperparameters, final map refit.',CV+(p('c','Regularization C',10,.01,1000),p('gamma','RBF gamma',.25,.0001,100))),
m('spatial_lda_cv','Classification','Shrinkage LDA with spatial cross-validation',SPECTRUM+(('training','class'),),'class','Equal prior, training-only covariance, every labeled pixel held out once.',CV+(p('shrinkage','Covariance shrinkage',.1,.001,1),)),
m('atmospheric_reflectance','Preprocessing','Conditional Lambertian atmospheric correction',refl('toa','path')+(('transmission','transmittance'),('spherical_albedo','fraction')),'reflectance','Supplied band atmospheric path reflectance, combined transmission and spherical albedo; no aerosol retrieval.'),
m('robust_harmonization','Preprocessing','Robust cross-scene radiometric harmonization',refl('candidate','reference')+(('calibration','class'),),'reflectance','Stable mask 1 fits Huber regression, mask 2 evaluates independent labeled pixels.',(p('huber_k','Huber tuning constant',1.345,.5,5),p('iterations','Maximum iterations',80,10,200,True))),
m('irmad','Change','Iteratively reweighted MAD',refl('red_before','nir_before','swir_before','red_after','nir_after','swir_after'),'index','Chi-square survival reweighting of canonical alteration; convergence reported; no calibrated significance.',(p('iterations','Maximum iterations',60,2,100,True),p('tolerance','Canonical correlation tolerance',.0001,1e-8,.01))),
m('cloud_buffer','Quality','Conservative cloud and invalid-pixel buffer',(('qa','class'),),'class','Binary clear mask, Euclidean disk in pixel units; original NoData retained.',(p('radius','Buffer radius (cells)',2,1,20,True),)),
m('series_break_time','Time Series','Single mean-shift breakpoint time',numeric('date1','date2','date3','date4','date5','date6'),'time','Least-squares single mean shift; actual time midpoint; descriptive.',(p('min_segment','Minimum observations per segment',3,2,16,True),)),
m('series_break_jump','Time Series','Single breakpoint mean shift',numeric('date1','date2','date3','date4','date5','date6'),'source','After minus before segment mean at best split.',(p('min_segment','Minimum observations per segment',3,2,16,True),)),
m('series_break_strength','Time Series','Single breakpoint explained variance',numeric('date1','date2','date3','date4','date5','date6'),'fraction','Fraction of centered sum of squares explained by one split; not a p-value.',(p('min_segment','Minimum observations per segment',3,2,16,True),)),
m('sar_gamma_map','Radar','Gamma MAP adaptive speckle filtering',(('power','power'),),'linear_power','Calibrated intensity; Gamma multiplicative noise with specified equivalent number of looks.',(p('radius','Window radius (cells)',2,1,10,True),p('enl','Equivalent number of looks',4,1,1000))),
m('sar_log_change','Radar','Paired SAR log-ratio change',(('before','power'),('after','power')),'dB','Comparable acquisition geometry, polarization and power calibration; positive paired observations.'),
m('sar_gamma0_flat','Radar','Flat-earth sigma0 to gamma0',(('sigma0','power'),('incidence','slope')),'linear_power','Sigma0 divided by cosine of incidence angle; flat-earth normalization only, not terrain flattening.'),
m('mad_distance','Change','Canonical multivariate alteration distance',refl('red_before','nir_before','swir_before','red_after','nir_after','swir_after')+(('calibration','class'),),'index','Canonical correlation on designated stable pixels; three standardized alteration components; descriptive distance, no calibrated probability.'),
m('surface_temperature_rte','Thermal','Atmosphere-corrected single-channel LST',(('radiance','radiance'),('emissivity','emissivity'),('transmittance','transmittance'),('upwelling','radiance'),('downwelling','radiance')),'K','External band-specific atmospheric radiance and transmittance required.',(p('k1','K1 radiance constant',774.8853,.000001,1e7),p('k2','K2 temperature constant',1321.0789,.000001,1e7))),
m('topographic_c','Preprocessing','Terrain illumination C correction',(('reflectance','reflectance'),('slope','slope'),('aspect','aspect'),('calibration','class')),'reflectance','Calibration mask=1 in homogeneous cover; grid-referenced solar geometry; shaded cells excluded.',(p('solar_zenith','Solar zenith (degrees)',30,0,85),p('solar_azimuth','Solar azimuth (grid degrees)',135,0,360),p('min_cosine','Minimum illumination cosine',.1,.01,1))),
m('ndvi_uncertainty','Optical','NDVI propagated standard uncertainty',refl('nir','red')+(('nir_sd','nonnegative'),('red_sd','nonnegative')),'index','First-order delta method; supplied reflectance SDs and same-cell correlation.',(p('correlation','NIR/red error correlation',0,-1,1),p('min_sum','Minimum absolute band sum',.01,1e-8,1))),
m('change_vector','Change','Multiband change vector magnitude',refl('red_before','nir_before','swir_before','red_after','nir_after','swir_after'),'reflectance','Euclidean length of paired spectral change vector.'),
m('change_mahalanobis','Change','Stable-reference covariance change distance',refl('red_before','nir_before','swir_before','red_after','nir_after','swir_after')+(('calibration','class'),),'index','Stable calibration mask=1, covariance shrinkage; descriptive multivariate distance.'),
m('spatial_lda','Classification','Regularized LDA with spatial holdout',SPECTRUM+(('training','class'),),'class','Equal-prior shared covariance classifier; disjoint spatial blocks and optional training buffer.',(p('block_m','Block width (m)',100,1,100000),p('folds','Spatial fold count',5,3,10,True),p('heldout_fold','Held-out fold',0,0,9,True),p('buffer_blocks','Training exclusion buffer (blocks)',0,0,1,True),p('shrinkage','Covariance shrinkage',.1,.001,1))),
m('series_median','Time Series','Multi-acquisition median composite',numeric('date1','date2','date3','date4','date5','date6'),'source','6–64 aligned acquisitions; at least two valid observations.'),
m('series_count','Time Series','Multi-acquisition observation count',numeric('date1','date2','date3','date4','date5','date6'),'count','6–64 aligned acquisitions; count of quality-screened observations.'),
m('series_slope','Time Series','Multi-acquisition linear trend',numeric('date1','date2','date3','date4','date5','date6'),'source/time','6–64 aligned acquisitions with actual times and per-pixel missingness.'),
m('series_amplitude','Time Series','Seasonal harmonic amplitude',numeric('date1','date2','date3','date4','date5','date6'),'source','Linear trend plus first harmonic, fixed period; at least six valid observations.',(p('period','Seasonal period (time units)',365,.0001,1e6),)),
m('series_harmonic_rmse','Time Series','Seasonal model residual RMSE',numeric('date1','date2','date3','date4','date5','date6'),'source','In-sample seasonal model residual; not forecast validation.',(p('period','Seasonal period (time units)',365,.0001,1e6),)),
m('true_color','Spectral','True-color reflectance composite',refl('red','green','blue'),'reflectance','Calibrated [0,1] reflectance RGB channels; common validity mask, no display stretch.'),
m('false_color','Spectral','False-color NIR / red / green composite',refl('nir','red','green'),'reflectance','Calibrated [0,1] reflectance channels assigned to RGB in NIR/red/green order; no display stretch.'),
m('calibrated_reflectance','Preprocessing','Calibrated reflectance export',refl('band'),'reflectance','Explicit source scale and offset; no atmospheric correction.'),
m('align_continuous','Preprocessing','Align continuous band (bilinear)',(('target','template'),('source','numeric')),'source_band','Explicit reprojection to target grid; target NoData retained; no QA in this alignment operation.'),
m('align_categorical','Preprocessing','Align categorical band (nearest)',(('target','template'),('source','class')),'class','Nearest-neighbor reprojection to target grid; target NoData retained; no QA in this alignment operation.'),
m('ndvi_change','Change','NDVI change (after minus before)',refl('nir_before','red_before','nir_after','red_after'),'index','Paired comparable surface reflectance; separate acquisition quality masks recommended.'),
m('dnbr','Change','Differenced NBR (before minus after)',refl('nir_before','swir_before','nir_after','swir_after'),'index','Pre-fire NBR minus post-fire NBR; not automatically calibrated burn severity.'),
m('sar_lee','Radar','Lee-type adaptive speckle filter',(('power','power'),),'linear_power','Local multiplicative noise model with supplied equivalent number of looks; not a terrain correction.',(p('radius','Window radius (cells)',2,1,10,True),p('enl','Equivalent number of looks',4,1,1000))),
m('temporal_sen','Time Series','Theil–Sen temporal slope',TIMES,'source/time','Median pairwise slope at supplied acquisition times; requires at least three valid observations.',TIME),
m('temporal_trend_se','Time Series','OLS temporal slope standard error',TIMES,'source/time','Conditional classical OLS standard error, at least three valid observations; independent homoscedastic residual assumption.',TIME),
m('spectral_unmix','Spectral','Fully constrained spectral abundance',SPECTRUM+(('training','class'),),'fraction','Endmember class means from labeled pixels; nonnegative fractions sum to one, selected class abundance.',(p('target_class','Target endmember class',1,1,65535,True),)),
m('spectral_unmix_rmse','Spectral','Spectral mixture reconstruction RMSE',SPECTRUM+(('training','class'),),'reflectance','Residual RMSE of fully constrained linear mixture fit; not independent classification accuracy.'),
m('stratified_accuracy','Classification','Map-stratified area-adjusted accuracy',(('prediction','class'),('reference','class')),'','Reference NoData outside validation sample; assumes simple random sampling within each mapped class, reports area-adjusted matrix and OA SE; design must be user-verified.'),
m('ndvi','Optical','NDVI — vegetation',refl('nir','red'),'index',OPT),
m('evi','Optical','EVI — enhanced vegetation',refl('nir','red','blue'),'index',OPT),
m('evi2','Optical','EVI2 — two-band enhanced vegetation',refl('nir','red'),'index',OPT),
m('savi','Optical','SAVI — soil adjusted vegetation',refl('nir','red'),'index',OPT,(p('soil_l','Soil adjustment L',.5,0,1),)),
m('msavi2','Optical','MSAVI2 — modified soil adjustment',refl('nir','red'),'index',OPT),
m('gndvi','Optical','GNDVI — green vegetation',refl('nir','green'),'index',OPT),
m('ndre','Optical','NDRE — red-edge vegetation',refl('nir','rededge'),'index',OPT),
m('ndwi','Optical','NDWI — open water (McFeeters)',refl('green','nir'),'index',OPT),
m('mndwi','Optical','MNDWI — modified water',refl('green','swir1'),'index',OPT),
m('ndmi','Optical','NDMI — vegetation moisture',refl('nir','swir1'),'index',OPT),
m('nbr','Optical','NBR — normalized burn ratio',refl('nir','swir2'),'index',OPT),
m('nbr2','Optical','NBR2 — SWIR burn ratio',refl('swir1','swir2'),'index',OPT),
m('ndbi','Optical','NDBI — built-up index',refl('swir1','nir'),'index',OPT),
m('bsi','Optical','BSI — bare soil',refl('swir1','red','nir','blue'),'index',OPT),
m('ndsi','Optical','NDSI — snow',refl('green','swir1'),'index',OPT),
m('arvi','Optical','ARVI — atmospherically resistant vegetation',refl('nir','red','blue'),'index',OPT),
m('osavi','Optical','OSAVI — optimized soil adjusted vegetation',refl('nir','red'),'index',OPT),
m('simple_ratio','Optical','Simple NIR / red ratio',refl('nir','red'),'index',OPT),
m('nirv','Optical','NIRv — NIR vegetation reflectance',refl('nir','red'),'reflectance',OPT),
m('ci_green','Optical','Green chlorophyll index',refl('nir','green'),'index',OPT),
m('sentinel_clear','Quality','Sentinel-2 SCL conservative clear mask',(('qa','class'),),'class','Retains only SCL 4 vegetation, 5 non-vegetated, 6 water; 0 is NoData.'),
m('landsat_clear','Quality','Landsat 8/9 Collection 2 QA_PIXEL clear mask',(('qa','class'),),'class','Rejects fill, dilated cloud, cirrus, cloud, shadow and snow (bits 0–5); water retained.'),
m('landsat_unsaturated','Quality','Landsat QA_RADSAT conservative mask',(('qa','class'),),'class','Only zero flags are retained; rejects any saturation or other flagged condition.'),
m('difference','Change','After minus before',numeric('before','after'),'source','Comparable quantity and identical units; complete paired observations.'),
m('relative_change','Change','Relative change (%)',numeric('before','after'),'percent','100*(after-before)/abs(before); zero baseline becomes NoData.'),
m('change_classes','Change','Thresholded change classes',numeric('before','after'),'class','0 stable, 1 decrease, 2 increase; strict threshold in source units.',(T,)),
m('transition_matrix','Change','Categorical transition matrix',CLASSES,'','Class pairs and observed area; projected metre grid, no design-based area adjustment.'),
m('brightness_temperature','Thermal','Planck brightness temperature',(('radiance','radiance'),),'K','At-sensor radiance and sensor-specific K1/K2; not land surface temperature.',(p('k1','K1 radiance constant',774.8853,.000001,1e7),p('k2','K2 temperature constant (K)',1321.0789,.000001,1e7))),
m('emissivity_temperature','Thermal','Emissivity-corrected temperature approximation',(('temperature','kelvin'),('emissivity','emissivity')),'K','Single-wavelength emissivity correction of brightness temperature; not a full atmospheric LST retrieval.',(p('wavelength_um','Effective wavelength (µm)',10.9,3,20),)),
m('temperature_celsius','Thermal','Kelvin to Celsius',(('temperature','kelvin'),),'degC','Physical conversion, not a new retrieval.'),
m('sar_db','Radar','Linear radar power to dB',(('power','power'),),'dB','Calibrated linear power, not amplitude; zero becomes NoData.'),
m('sar_linear','Radar','Radar dB to linear power',(('backscatter','db'),),'linear_power','Inverse power logarithm; not radiometric calibration.'),
m('sar_ratio','Radar','Cross/co-polarized power ratio',(('cross','power'),('co','power')),'ratio','Comparable calibrated linear power; zero co-polarized denominator excluded.'),
m('dualpol_rvi','Radar','Dual-pol radar vegetation index proxy',(('cross','power'),('co','power')),'index','4*cross/(co+cross), a dual-pol proxy, not full-polarimetric RVI.'),
m('temporal_mean','Time Series','Four-date mean',TIMES,'source','Comparable quantity and units; available observations, at least two per pixel.'),
m('temporal_median','Time Series','Four-date median composite',TIMES,'source','Comparable quantity and units; available observations, at least two per pixel.'),
m('temporal_count','Time Series','Valid observation count',TIMES,'count','Counts finite, quality-screened acquisitions; zero is valid count.'),
m('temporal_trend','Time Series','OLS temporal slope',TIMES,'source/time','Actual numeric acquisition times; per-pixel OLS on at least three valid observations.',TIME),
m('pca','Spectral','Four-band PCA component',SPECTRUM,'reflectance','Complete-case centered covariance PCA; signs anchored by largest loading; no standardization.',(p('component','Principal component',1,1,4,True),)),
m('spectral_angle','Spectral','Spectral angle between acquisitions',refl('red_before','nir_before','swir_before','red_after','nir_after','swir_after'),'degrees','Three comparable spectral bands per acquisition; angular difference, not classification.'),
m('minimum_distance','Classification','Supervised minimum-distance classification',SPECTRUM+(('training','class'),),'class','Positive integer training labels; class centroids in reflectance space, no independent accuracy implied.'),
m('classification_accuracy','Classification','Classification reference agreement',(('prediction','class'),('reference','class')),'','Paired independent reference labels supplied by user; unweighted confusion matrix, overall accuracy, precision, recall and kappa; not area-adjusted.'),
)
BY_ID={x.id:x for x in METHODS}
assert len(BY_ID)==len(METHODS)

def catalog():
    return [{'id':x.id,'group':x.group,'title':x.title,'roles':[{'id':r,'quantity':q} for r,q in x.roles],
             'parameters':[dict(zip(('name','label','default','minimum','maximum','integer'),v)) for v in x.parameters],
             'unit':x.unit,'assumption':x.assumption,'variable_series':x.id in SERIES_IDS} for x in METHODS]
