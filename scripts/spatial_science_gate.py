"""Evidence gate for the declared spatial science numerical acceptance scope."""
import argparse,json,sys
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from analysis.science_catalog import BY_ID

def expected_tests():
    groups={
        'test_vector_area_oracles':'intersection union difference symmetric_difference convex_hull',
        'test_vector_metric_oracles':'buffer centroid simplify spatial_join nearest_join point_centers point_nearest_neighbor sample_polygon',
        'test_cell_arithmetic_oracles':'raster_sum raster_difference raster_ratio raster_mean raster_sd raster_min raster_max',
        'test_focal_against_independent_window_reduction':'focal_mean focal_sd focal_min focal_max focal_range',
        'test_threshold_and_grid_aggregation':'raster_threshold aggregate_mean aggregate_sum',
        'test_sample_design_conserves_population':'sample_random sample_systematic sample_stratified sample_spatial_balanced',
        'test_spatial_statistics_oracles':'global_moran global_geary join_count raster_quantile',
        'test_decision_methods_known_dominance_and_consistency':'weighted_overlay topsis ahp_overlay constraint_mask pareto_cells',
        'test_integrated_operators_analytic_spatial_fixture':'zonal_statistics zonal_classes clip_raster rasterize extract_points point_kernel_density polygonize',
        'test_explicit_resampling_and_class_breaks':'resample_grid reclassify',
        'test_local_statistics_and_multiplicity':'local_moran getis_ord_gi_star',
        'test_research_depth_oracles':'distance_moran knn_moran multiscale_moran empirical_variogram difference_uncertainty spatial_lag_regression geographically_weighted_regression',
        'test_advanced_spatial_oracles':'raster_distance focal_quantile directional_lag_scan bivariate_moran robust_overlay blocked_regression point_ellipse zonal_quantiles',
    }
    out={method:f'{test}[{method}]' for test,methods in groups.items() for method in methods.split()}
    if set(out)!=set(BY_ID):raise RuntimeError('Every registered method must have an explicit numeric oracle.')
    return out

def required_tests():
    return ['test_contract_count_and_invalid_input_rejections','test_spatial_gdal_cli_alignment_reference','test_spatial_medium_grid_mass_and_mask_conservation','test_overlay_shared_edges_preserve_area_and_valid_inverse_projection','test_queen_weights_and_permutation_table','test_dirichlet_analytic_uncertainty_opposed_criteria','test_independent_distance_reference_with_nodata','test_spatial_randomization_exact_reference','test_integrated_coverage_with_nodata','test_decision_extreme_weight_normalization','test_sampling_design_expected_totals','test_sparse_permutation_population_budget','test_full_grid_figure_and_output_provenance','test_large_separable_neighborhood_against_brute_force','test_research_depth_invalid_and_model_figure',*[f'test_spatial_actual_result_figure_pipeline[{i}]' for i in ('null','lag','sample','prediction','coverage')]]

def evaluate(path):
    root=ET.parse(path).getroot()
    status={}
    for case in root.iter('testcase'):
        name=case.attrib.get('name','')
        passed=not any(case.find(tag) is not None for tag in ('failure','error','skipped'))
        status[name]=passed and status.get(name,True)
    required=required_tests()
    common=all(status.get(test,False) for test in required)
    cases=[{'method':method,'oracle':test,'oracle_passed':status.get(test,False),
            'numerical_fixture_score':90*int(status.get(test,False))+10*int(common)}
           for method,test in sorted(expected_tests().items())]
    passed=common and all(c['oracle_passed'] for c in cases)
    return {'passed':passed,'methods':len(cases),'methods_passing':sum(c['oracle_passed'] for c in cases),
            'minimum_fixture_score':min(c['numerical_fixture_score'] for c in cases),'required_minimum_score':95,
            'common_checks':{test:status.get(test,False) for test in required},
            'scope':'Method-specific analytic fixtures, independent comparisons, statistical design, numerical safeguards, and actual-result figure pipelines. This score measures declared test evidence, not field accuracy or production maturity.',
            'results':cases}

def main():
    p=argparse.ArgumentParser();p.add_argument('--junit',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    result=evaluate(args.junit);Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(f"Spatial science methods: {result['methods_passing']}/{result['methods']}; minimum numerical fixture score: {result['minimum_fixture_score']}/100")
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
