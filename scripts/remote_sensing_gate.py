"""Reject missing, skipped or failing scientific acceptance evidence."""
import argparse
import json
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from imagery.remote_catalog import BY_ID

def expected_tests():
    groups={
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
    return ['test_sensor_calibration_and_quality_roles','test_thermal_landsat_surface_temperature_preset',
            'test_remote_invalid_inputs_and_recovery','test_temporal_independent_quality_masks',
            'test_remote_to_spatial_and_figure_workflow','test_remote_medium_grid_and_undefined_ratio','test_remote_gdal_reference','test_rgb_actual_figure_workflow','test_windowed_scene_above_inline_budget']

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
