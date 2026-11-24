"""Typed inventory shared by the human workbench and future AI tool registry.

All operations are explicit, deterministic except seeded sampling/permutations.
The catalog is an interface contract, not a numerical accuracy certificate.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Method:
    id:str
    group:str
    title:str
    source:str
    minimum:int
    maximum:int
    parameters:tuple
    result:str
    assumption:str

# name, label, default, minimum, maximum, integer
D=('distance_m','Distance (m)',100,0.01,100000,False)
R=('radius','Neighborhood radius (cells)',1,1,20,True)
N=('count','Sample count',100,1,10000,True)
S=('seed','Random seed',42,0,4294967295,True)
K=('k','Nearest neighbors',4,1,32,True)
P=('permutations','Permutations',199,99,999,True)
B=('bandwidth_m','Bandwidth (m)',100,0.01,100000,False)
T=('threshold','Threshold',0,-1e100,1e100,False)
Q=('quantile','Quantile',.5,0,1,False)
F=('factor','Integer aggregation factor',2,2,16,True)
A=('alpha','Significance level',.05,.001,.2,False)

def m(id,group,title,source,minimum,maximum,parameters,result,assumption):
    return Method(id,group,title,source,minimum,maximum,parameters,result,assumption)

METHODS=(
m('intersection','Vector','Intersection','vector',2,2,(),'vector','Planar topology in explicitly selected projected metre CRS.'),
m('union','Vector','Union / dissolve all','vector',1,2,(),'vector','Union removes overlaps; source attributes are not aggregated.'),
m('difference','Vector','Difference','vector',2,2,(),'vector','Subtract second layer union from first.'),
m('symmetric_difference','Vector','Symmetric difference','vector',2,2,(),'vector','Exclusive spatial coverage.'),
m('buffer','Vector','Metric buffer','vector',1,1,(D,),'vector','Projected metric buffer, not cadastral legal setback.'),
m('convex_hull','Vector','Convex hull','vector',1,1,(),'vector','Minimum convex envelope of the full input.'),
m('centroid','Vector','Feature centroid','vector',1,1,(),'vector','Planar geometric centroid; may fall outside polygon.'),
m('simplify','Vector','Topology-preserving simplification','vector',1,1,(D,),'vector','Per-feature topology preserved; shared boundaries may diverge.'),
m('spatial_join','Vector','Intersection spatial join','vector',2,2,(),'table','One record per intersecting pair; touching counts.'),
m('nearest_join','Vector','Nearest feature join','vector',2,2,(),'table','Projected geometric distance; deterministic index tie break.'),
m('point_ellipse','Vector','Covariance standard-distance ellipse','vector',1,1,(),'vector','One standard deviation along population covariance eigenaxes; descriptive, not confidence region.'),
m('raster_sum','Raster','Raster sum','raster',2,8,(),'raster','Exactly aligned grids, identical known units.'),
m('raster_difference','Raster','Raster difference','raster',2,2,(),'raster','First minus second; identical known units.'),
m('raster_ratio','Raster','Raster ratio','raster',2,2,(),'raster','Same units; zero denominators become NoData.'),
m('raster_mean','Raster','Cellwise mean','raster',2,8,(),'raster','Complete cases; same units.'),
m('raster_sd','Raster','Cellwise population SD','raster',2,8,(),'raster','Population dispersion across aligned inputs.'),
m('raster_min','Raster','Cellwise minimum','raster',2,8,(),'raster','Complete cases; same units.'),
m('raster_max','Raster','Cellwise maximum','raster',2,8,(),'raster','Complete cases; same units.'),
m('raster_threshold','Raster','Binary threshold','raster',1,1,(T,),'raster','One where value >= threshold, zero elsewhere; NoData retained.'),
m('focal_mean','Raster','Focal mean','raster',1,1,(R,),'raster','Square neighborhood including center; available finite neighbors.'),
m('focal_sd','Raster','Focal population SD','raster',1,1,(R,),'raster','Stable central moments; center must be valid.'),
m('focal_min','Raster','Focal minimum','raster',1,1,(R,),'raster','Finite neighbors in a square window.'),
m('focal_max','Raster','Focal maximum','raster',1,1,(R,),'raster','Finite neighbors in a square window.'),
m('focal_range','Raster','Focal range','raster',1,1,(R,),'raster','Maximum minus minimum, finite neighbors.'),
m('aggregate_mean','Raster','Block aggregation mean','raster',1,1,(F,),'raster','Exact complete blocks; missing source values excluded, no incomplete edge blocks.'),
m('resample_grid','Raster','Align source to reference grid','raster',2,2,(),'raster','Explicit nearest or bilinear resampling of second grid onto first; reference NoData retained.'),
m('reclassify','Raster','Classify using numerical breaks','raster',1,1,(),'raster','Half-open intervals [lower, upper), final upper included; out-of-range cells become NoData.'),
m('aggregate_sum','Raster','Block aggregation sum','raster',1,1,(F,),'raster','Additive cell quantities only; exact complete blocks.'),
m('raster_distance','Raster','Exact Euclidean proximity','raster',1,1,(),'raster','Binary target cells; exact projected cell-center Euclidean distance; NoData is not a barrier.'),
m('focal_quantile','Raster','Robust neighborhood quantile','raster',1,1,(R,Q),'raster','Finite-neighbor quantile, valid center; square window.'),
m('sample_random','Sampling','Uniform random cell sample','raster',1,1,(N,S),'table','Without replacement among valid cells.'),
m('sample_systematic','Sampling','Systematic cell sample','raster',1,1,(N,S),'table','Random start with systematic spacing in row-major valid-cell order.'),
m('sample_stratified','Sampling','Stratified categorical sample','raster',1,1,(N,S),'table','Approximately equal class allocation; explicit design weights.'),
m('sample_spatial_balanced','Sampling','Spatially balanced cell sample','raster',1,1,(N,S),'table','Recursive longest-axis spatial partition with one random cell per partition.'),
m('sample_polygon','Sampling','Uniform polygon point sample','vector',1,1,(N,S),'vector','Uniform projected area; rejection sampling with bounded attempts.'),
m('global_moran','Statistics','Global Moran I','raster',1,1,(P,S),'table','Rook or queen adjacency, symmetric binary weights, exchangeability permutation null.'),
m('local_moran','Statistics','Local Moran I and conditional significance','raster',1,1,(P,S,A),'raster','Rook adjacency, conditional randomization and dependence-robust BY adjustment.'),
m('getis_ord_gi_star','Statistics','Getis–Ord Gi* hotspot inference','raster',1,1,(P,S,A),'raster','Rook neighborhood plus focal cell; random-label permutation p values, BY adjustment.'),
m('global_geary','Statistics','Global Geary C','raster',1,1,(P,S),'table','Rook or queen adjacency, symmetric binary weights, exchangeability permutation null.'),
m('join_count','Statistics','Binary join counts','raster',1,1,(P,S),'table','Binary 0/1 cells, undirected rook or queen joins, permutation null.'),
m('point_nearest_neighbor','Statistics','Point nearest-neighbor distances','vector',1,1,(),'table','Observed distances only; no implicit study area or CSR significance.'),
m('point_kernel_density','Statistics','Gaussian point intensity','integrated',1,1,(B,),'raster','Point intensity per square metre; Gaussian truncated at 4 sigma, no edge correction.'),
m('point_centers','Statistics','Mean center and standard distance','vector',1,1,(),'vector','Unweighted projected point center and RMS radial distance.'),
m('raster_quantile','Statistics','Raster quantile summary','raster',1,1,(Q,),'table','All valid cells, linear quantile interpolation.'),
m('directional_lag_scan','Statistics','Directional spatial dependence by distance','raster',1,1,(('max_lag','Maximum lag (cells)',5,1,30,True),),'table','Directional paired-cell empirical semivariance, covariance and correlation, no independence assumption.'),
m('bivariate_moran','Statistics','Cross-variable global Moran','raster',2,2,(P,S),'table','Row-standardized rook lag of second variable; permutation null randomizes second variable; no causal inference.'),
m('weighted_overlay','Decision','Weighted normalized overlay','raster',2,8,(),'raster','Min-max normalization with explicit benefit/cost direction; all inputs valid.'),
m('topsis','Decision','TOPSIS spatial suitability','raster',2,8,(),'raster','Vector normalization, explicit benefit/cost criteria and positive weights.'),
m('ahp_overlay','Decision','AHP weighted spatial overlay','raster',2,8,(),'raster','Reciprocal pairwise matrix, principal eigenvector, CR <= 0.10.'),
m('constraint_mask','Decision','Constrained suitability mask','raster',2,2,(),'raster','First grid values retained only where second is binary one.'),
m('pareto_cells','Decision','Two-criterion Pareto cells','raster',2,2,(),'raster','Exact nondominance of complete cells; explicit maximize/minimize.'),
m('robust_overlay','Decision','Weight-uncertainty spatial suitability','raster',2,8,(('draws','Monte Carlo draws',200,20,1000,True),('concentration','Dirichlet concentration',40,1,10000,False),('threshold','Suitability threshold',.7,0,1,False),S),'raster','Dirichlet weight uncertainty, fixed normalized criteria; conditional probability, not event probability.'),
m('blocked_regression','Integrated','Spatially buffered raster regression','raster',2,8,(('block_size_m','Spatial block size (m)',100,1,100000,False),('folds','Validation folds',5,3,10,True),('ridge_penalty','Ridge penalty',1,0,100000,False),('buffer_m','Exclusion buffer (m)',0,0,100000,False)),'raster','First raster response; remaining predictors; complete-case out-of-fold prediction with fold-local preprocessing.'),
m('zonal_statistics','Integrated','Area-weighted zonal statistics','integrated',1,1,(),'table','Exact fractional cell overlap in the raster projected CRS.'),
m('zonal_quantiles','Integrated','Area-weighted zonal quantiles','integrated',1,1,(Q,),'table','Inverse weighted empirical CDF using exact positive overlap areas; no interpolation.'),
m('zonal_classes','Integrated','Area-weighted class coverage','integrated',1,1,(),'table','Exact fractional overlap, integral class codes.'),
m('clip_raster','Integrated','Clip raster by polygon','integrated',1,1,(),'raster','Cell-center inclusion; no interpolation; original grid retained.'),
m('rasterize','Integrated','Polygon occupancy raster','integrated',1,1,(),'raster','Cell-center inclusion, template validity mask retained.'),
m('extract_points','Integrated','Extract raster at points','integrated',1,1,(),'table','Nearest containing cell; outside/NoData becomes null.'),
m('polygonize','Integrated','Polygonize categorical raster','raster',1,1,(),'vector','Four-connected integer classes, original grid boundaries.'),
m('distance_moran','Statistics','Distance-weighted global Moran I','raster',1,1,(D,('power','Inverse distance exponent',1,0,3,False),P,S),'table','Projected distance-band graph; row-standardized weights; random-label null; isolates reported.'),
m('knn_moran','Statistics','K-nearest-neighbor Moran I','raster',1,1,(K,('power','Inverse distance exponent',0,0,3,False),P,S),'table','Directed KNN graph with stable ties; row-standardized weights; random-label null.'),
m('multiscale_moran','Statistics','Multiscale spatial dependence','raster',1,1,(('max_factor','Maximum aggregation factor',4,2,16,True),),'table','Native-origin block means, incomplete edge blocks discarded; descriptive scale dependence.'),
m('empirical_variogram','Statistics','Isotropic empirical semivariogram','raster',1,1,(D,('bins','Lag bins',10,2,30,True)),'table','Matheron empirical semivariance for unique metric cell pairs; no fitted model.'),
m('fit_exponential_variogram','Statistics','Exponential semivariogram calibration','raster',1,1,(D,('bins','Lag bins',10,4,30,True),('min_range_m','Minimum covariance range (m)',1,.01,100000,False),('max_range_m','Maximum covariance range (m)',1000,.02,100000,False)),'table','Nonnegative nugget and partial sill; pair-count weighted least squares; explicit range search; use diagnostics before kriging.'),
m('difference_uncertainty','Integrated','Difference uncertainty propagation','raster',4,4,(('correlation','Same-cell error correlation',0,-1,1,False),),'raster','Input order: A, B, standard uncertainty of A, standard uncertainty of B; matching physical units.'),
m('spatial_lag_regression','Integrated','Spatial lag regression (2SLS)','raster',2,8,(),'raster','Response first, predictors next; rook row-standardized spatial lag; WX and W²X instruments; conditional structural fit, not forecast.'),
m('geographically_weighted_regression','Integrated','Geographically weighted leave-one-out regression','raster',2,8,(B,),'raster','Response first; fixed Gaussian bandwidth in metres; leave-one-out local prediction, not spatial-block validation.'),
m('ordinary_kriging','Integrated','Ordinary kriging prediction','raster',2,2,(('range_m','Covariance e-folding range (m)',100,.01,100000,False),('sill','Partial sill (observation unit squared)',1,1e-12,1e100,False),('nugget_ratio','Nugget to partial sill ratio',.1,0,10,False)),'raster','First raster is target validity mask, second is sparse observations; exponential covariance with supplied parameters; latent prediction.'),
m('kriging_uncertainty','Integrated','Ordinary kriging prediction SD','raster',2,2,(('range_m','Covariance e-folding range (m)',100,.01,100000,False),('sill','Partial sill (observation unit squared)',1,1e-12,1e100,False),('nugget_ratio','Nugget to partial sill ratio',.1,0,10,False)),'raster','Target mask first, sparse observations second; conditional latent-process SD with fixed exponential covariance parameters.'),
m('spatial_error_regression','Integrated','Spatial error regression (Gaussian ML)','raster',2,8,(('lambda_bound','Absolute lambda search bound',.95,.1,.99,False),),'raster','Response first; rook standardized spatial-error process; concentrated Gaussian ML, conditional coefficient standard errors.'),
m('difference_probability','Integrated','Gaussian difference exceedance probability','raster',4,4,(('correlation','Same-cell error correlation',0,-1,1,False),T),'raster','A, B, standard uncertainty A, standard uncertainty B; strict exceedance of threshold under specified marginal Gaussian errors.'),
m('sample_srs_estimation','Sampling','Finite-population simple random estimation','raster',1,1,(N,S),'table','SRS without replacement; design-based mean/total standard errors with finite population correction.'),
)
VALIDATION_P=(('block_m','Spatial block width (m)',100,1,1000000,False),('replicates','Bootstrap replicates',499,199,2000,True),S)
METHODS=METHODS+(
m('blocked_reference_accuracy','Statistics','Spatial block reference accuracy','raster',2,2,VALIDATION_P,'raster','Prediction and reference; paired block bootstrap confidence intervals for bias, MAE and RMSE.'),
m('blocked_model_comparison','Statistics','Paired spatial block model comparison','raster',3,3,VALIDATION_P,'raster','First estimate, second estimate, reference; shared blocks and paired bootstrap for differences in accuracy.'),
)
BY_ID={method.id:method for method in METHODS}
assert len(BY_ID)==len(METHODS)==75

def catalog():
    return [{'id':m.id,'group':m.group,'title':m.title,'source':m.source,
             'minimum':m.minimum,'maximum':m.maximum,
             'parameters':[dict(zip(('name','label','default','minimum','maximum','integer'),p)) for p in m.parameters],
             'result':m.result,'assumption':m.assumption,
             'requires_neighborhood':m.id in {'global_moran','global_geary','join_count'},
             'requires_local_view':m.id in {'local_moran','getis_ord_gi_star'},
             'requires_breaks':m.id=='reclassify','requires_resampling':m.id=='resample_grid',
             'requires_weights':m.id in {'weighted_overlay','topsis','robust_overlay'},
             'requires_pairwise':m.id=='ahp_overlay',
             'requires_directions':m.id in {'weighted_overlay','topsis','ahp_overlay','pareto_cells','robust_overlay'},
             'requires_robust_view':m.id=='robust_overlay', 'requires_regression_view':m.id in {'blocked_regression','spatial_lag_regression','geographically_weighted_regression','spatial_error_regression'}}
            for m in METHODS]
