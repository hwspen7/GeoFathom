"""Reject missing, skipped or failing scientific acceptance evidence."""
import argparse
import json
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from imagery.remote_catalog import BY_ID,WINDOWED_IDS,WINDOWED_CUBES

def expected_tests():
    groups={
        'test_two_track_los_decomposition_reference':'insar_east_displacement insar_up_displacement insar_east_sd insar_up_sd insar_east_up_correlation insar_geometry_condition',
        'test_wishart_change_independent_reference':'sar_wishart_statistic sar_wishart_p',
        'test_atmospheric_jacobian_reference':'atmospheric_reflectance_sd atmospheric_reflectance_condition',
        'test_quality_composite_reference':'quality_weighted_mean quality_weighted_sd quality_effective_count',
        'test_gamma_change_reference':'sar_gamma_change_p sar_gamma_ratio_low sar_gamma_ratio_high',
        'test_exact_overlap_reference':'align_overlap_mean align_overlap_coverage',
        'test_joint_research_reference':'joint_lai joint_cab joint_lai_sd joint_cab_sd joint_parameter_correlation joint_effective_hypotheses fusion_two_anchor fusion_anchor_disagreement cloud_calibrated_probability shadow_calibrated_probability',
        'test_anchored_phase_reference':'insar_phase_wls insar_relative_range',
        'test_advanced_analysis_ready_reference':'sar_dual_entropy sar_dual_purity sar_dual_minor_fraction brdf_ross_li fusion_support_temporal cloud_probability_model shadow_probability_model',
        'test_spectral_inference_reference':'spectral_rx spectral_mnf spectral_matched_filter lai_library_mean lai_library_sd lai_library_misfit',
        'test_resolution_and_reference_accuracy':'align_area_mean align_area_coverage continuous_reference_error binary_reference_error',
        'test_fusion_biophysical_reference':'fusion_gls fusion_gls_sd fusion_discrepancy canopy_lai canopy_fpar_proxy spectral_kmeans spectral_kmeans_distance',
        'test_cloud_shadow_reference':'cloud_shadow_candidates cloud_shadow_clear',
        'test_sar_complex_cloud_reference':'sar_calibrated_power insar_wrapped_phase insar_coherence cloud_candidates',
        'test_nested_spatial_reference':'spatial_nested_svm',
        'test_subpixel_registration_reference':'register_subpixel',
        'test_temporal_model_extension':'season_peak season_start season_end season_duration segmented_count segmented_first_break',
        'test_correlated_thermal_reference':'lst_correlated_uncertainty',
        'test_hyperspectral_reference':'spectral_absorption_depth spectral_absorption_center spectral_absorption_area spectral_endmembers',
        'test_physical_depth_reference':'lst_uncertainty sar_terrain_volume sar_terrain_validity register_translation',
        'test_blocked_classifier_reference':'spatial_rf_cv spatial_svm_cv spatial_lda_cv',
        'test_inference_reference':'atmospheric_reflectance robust_harmonization irmad cloud_buffer series_break_time series_break_jump series_break_strength',
        'test_sar_mad_reference':'sar_gamma_map sar_log_change sar_gamma0_flat mad_distance',
        'test_research_depth_reference':'surface_temperature_rte topographic_c ndvi_uncertainty change_vector change_mahalanobis spatial_lda series_median series_count series_slope series_amplitude series_harmonic_rmse',
        'test_rgb_reference':'true_color false_color',
        'test_advanced_remote_reference':'calibrated_reflectance align_continuous align_categorical ndvi_change dnbr sar_lee temporal_sen temporal_trend_se spectral_unmix spectral_unmix_rmse stratified_accuracy',
        'test_optical_reference':'ndvi evi evi2 savi msavi2 gndvi ndre ndwi mndwi ndmi nbr nbr2 ndbi bsi ndsi arvi osavi simple_ratio nirv ci_green',
        'test_quality_reference':'sentinel_clear landsat_clear landsat_unsaturated',
        'test_change_reference':'difference relative_change change_classes transition_matrix',
        'test_thermal_radar_reference':'brightness_temperature emissivity_temperature temperature_celsius sar_db sar_linear sar_ratio dualpol_rvi',
        'test_temporal_reference':'temporal_mean temporal_median temporal_count temporal_trend',
        'test_spectral_classification_reference':'pca spectral_angle minimum_distance classification_accuracy',
    }
    cases={method:f'{test}[{method}]' for test,methods in groups.items() for method in methods.split()}
    if set(cases)!=set(BY_ID):raise RuntimeError('Every catalog operation requires independent numerical evidence.')
    return cases

def required_tests():
    return ['test_atmospheric_lut_disk_interpolation_no_extrapolation','test_landsat_level1_metadata_calibration_and_quality','test_rpc_dem_orthorectification_known_height_shift','test_insar_shared_acquisition_gls_covariance','test_exact_spectral_response_and_no_extrapolation','test_insar_network_reference_and_disconnection','test_disk_non_nested_overlap_matches_inline_across_windows','test_satellite_affine_control_checkpoints_and_robustness','test_sensor_calibration_and_quality_roles','test_thermal_landsat_surface_temperature_preset',
            'test_remote_invalid_inputs_and_recovery','test_temporal_independent_quality_masks',
            'test_remote_to_spatial_and_figure_workflow','test_remote_medium_grid_and_undefined_ratio','test_remote_gdal_reference','test_rgb_actual_figure_workflow','test_windowed_scene_above_inline_budget','test_external_reference_comparison','test_new_research_figure_rendering','test_managed_disk_job_snapshot_and_cancellation',*[f'test_windowed_science_matches_inline_across_seams[{kind}]' for kind in ('sar_lee','sar_gamma_map','cloud_buffer','ndvi_change','surface_temperature_rte','fusion_gls','canopy_lai')],*[f'test_every_disk_method_matches_inline[{kind}]' for kind in sorted(WINDOWED_IDS-WINDOWED_CUBES)],*[f'test_disk_cube_matches_inline[{kind}]' for kind in sorted(WINDOWED_CUBES)],'test_disk_per_role_qa_and_calibration','test_stac_ndvi_streams_separate_bands_and_excludes_scl_clouds','test_stac_calibration_rejects_ambiguous_and_conflicting_metadata','test_public_fixture_transport_fallback_and_checksum','test_external_reference_streaming_across_windows','test_native_public_scene_crop_calibration','test_prosail_library_response_integration','test_joint_research_result_figures_render','test_joint_ambiguity_and_nonzero_anchor_disagreement','test_joint_prosail_adapter_retains_cab']

def evaluate(path):
    results={}
    for test in ET.parse(path).getroot().iter('testcase'):
        name=test.attrib.get('name','')
        ok=not any(test.find(tag) is not None for tag in ('skipped','error','failure'))
        results[name]=results.get(name,True) and ok
    methods={key:results.get(test,False) for key,test in expected_tests().items()}
    checks={test:results.get(test,False) for test in required_tests()}
    passed=all(methods.values()) and all(checks.values())
    return {'passed':passed,'methods':len(methods),'methods_passing':sum(methods.values()),
            'method_oracles':methods,'required_checks':checks,
            'scope':'Mandatory synthetic analytic reference and integrated workflow evidence. Not external sensor or field accuracy certification.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--junit',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    result=evaluate(args.junit);Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(f"Remote sensing method oracles: {result['methods_passing']}/{result['methods']}; required workflow checks: {sum(result['required_checks'].values())}/{len(result['required_checks'])}")
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
