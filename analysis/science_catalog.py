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
m('sample_random','Sampling','Uniform random cell sample','raster',1,1,(N,S),'table','Without replacement among valid cells.'),
m('sample_systematic','Sampling','Systematic cell sample','raster',1,1,(N,S),'table','Random start with systematic spacing in row-major valid-cell order.'),
m('sample_stratified','Sampling','Stratified categorical sample','raster',1,1,(N,S),'table','Approximately equal class allocation; explicit design weights.'),
m('sample_spatial_balanced','Sampling','Spatially balanced cell sample','raster',1,1,(N,S),'table','Recursive longest-axis spatial partition with one random cell per partition.'),
m('sample_polygon','Sampling','Uniform polygon point sample','vector',1,1,(N,S),'vector','Uniform projected area; rejection sampling with bounded attempts.'),
m('global_moran','Statistics','Global Moran I','raster',1,1,(P,S),'table','Rook adjacency, symmetric binary weights, exchangeability permutation null.'),
m('local_moran','Statistics','Local Moran I and conditional significance','raster',1,1,(P,S,A),'raster','Rook adjacency, conditional randomization and dependence-robust BY adjustment.'),
m('getis_ord_gi_star','Statistics','Getis–Ord Gi* hotspot inference','raster',1,1,(P,S,A),'raster','Rook neighborhood plus focal cell; random-label permutation p values, BY adjustment.'),
m('global_geary','Statistics','Global Geary C','raster',1,1,(P,S),'table','Rook adjacency, symmetric binary weights, exchangeability permutation null.'),
m('join_count','Statistics','Binary join counts','raster',1,1,(P,S),'table','Binary 0/1 cells, undirected rook joins, permutation null.'),
m('point_nearest_neighbor','Statistics','Point nearest-neighbor distances','vector',1,1,(),'table','Observed distances only; no implicit study area or CSR significance.'),
m('point_kernel_density','Statistics','Gaussian point intensity','integrated',1,1,(B,),'raster','Point intensity per square metre; Gaussian truncated at 4 sigma, no edge correction.'),
m('point_centers','Statistics','Mean center and standard distance','vector',1,1,(),'vector','Unweighted projected point center and RMS radial distance.'),
m('raster_quantile','Statistics','Raster quantile summary','raster',1,1,(Q,),'table','All valid cells, linear quantile interpolation.'),
m('weighted_overlay','Decision','Weighted normalized overlay','raster',2,8,(),'raster','Min-max normalization with explicit benefit/cost direction; all inputs valid.'),
m('topsis','Decision','TOPSIS spatial suitability','raster',2,8,(),'raster','Vector normalization, explicit benefit/cost criteria and positive weights.'),
m('ahp_overlay','Decision','AHP weighted spatial overlay','raster',2,8,(),'raster','Reciprocal pairwise matrix, principal eigenvector, CR <= 0.10.'),
m('constraint_mask','Decision','Constrained suitability mask','raster',2,2,(),'raster','First grid values retained only where second is binary one.'),
m('pareto_cells','Decision','Two-criterion Pareto cells','raster',2,2,(),'raster','Exact nondominance of complete cells; explicit maximize/minimize.'),
m('zonal_statistics','Integrated','Area-weighted zonal statistics','integrated',1,1,(),'table','Exact fractional cell overlap in the raster projected CRS.'),
m('zonal_classes','Integrated','Area-weighted class coverage','integrated',1,1,(),'table','Exact fractional overlap, integral class codes.'),
m('clip_raster','Integrated','Clip raster by polygon','integrated',1,1,(),'raster','Cell-center inclusion; no interpolation; original grid retained.'),
m('rasterize','Integrated','Polygon occupancy raster','integrated',1,1,(),'raster','Cell-center inclusion, template validity mask retained.'),
m('extract_points','Integrated','Extract raster at points','integrated',1,1,(),'table','Nearest containing cell; outside/NoData becomes null.'),
m('polygonize','Integrated','Polygonize categorical raster','raster',1,1,(),'vector','Four-connected integer classes, original grid boundaries.'),
)
BY_ID={method.id:method for method in METHODS}
assert len(BY_ID)==len(METHODS)==52

def catalog():
    return [{'id':m.id,'group':m.group,'title':m.title,'source':m.source,
             'minimum':m.minimum,'maximum':m.maximum,
             'parameters':[dict(zip(('name','label','default','minimum','maximum','integer'),p)) for p in m.parameters],
             'result':m.result,'assumption':m.assumption,
             'requires_local_view':m.id in {'local_moran','getis_ord_gi_star'},
             'requires_breaks':m.id=='reclassify','requires_resampling':m.id=='resample_grid',
             'requires_weights':m.id in {'weighted_overlay','topsis'},
             'requires_pairwise':m.id=='ahp_overlay',
             'requires_directions':m.id in {'weighted_overlay','topsis','ahp_overlay','pareto_cells'}}
            for m in METHODS]
