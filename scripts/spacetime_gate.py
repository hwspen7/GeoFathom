"""Reject missing, skipped or failed per-method scientific evidence."""
import sys
import xml.etree.ElementTree as ET
from analysis.spacetime_routes import METHODS
def main(path):
    tests=ET.parse(path).getroot().iter('testcase')
    passed={x.attrib['name'] for x in tests if not any(x.find(k) is not None for k in ('failure','error','skipped'))}
    expected={f'test_every_spacetime_method_reference[{k}]' for k in METHODS}
    expected|={'test_irregular_time_qa_calibration_and_alignment','test_state_space_against_batch_gaussian_conditioning','test_actual_science_figures_render','test_kriging_independent_dense_reference_and_holdout_isolation','test_harmonic_no_change_and_gap_boundary','test_hotspot_independent_score_and_panel_absorbed_covariate','test_panel_against_full_dummy_regression','test_advanced_figures_actual_products','test_universal_kriging_augmented_reference','test_rts_batch_gaussian_and_fitted_holdout_isolation'}
    missing=sorted(expected-passed)
    if missing:raise SystemExit('Missing passing evidence: '+', '.join(missing))
    print(f'Spatiotemporal method references: {len(METHODS)}/{len(METHODS)}; all mandatory scientific workflow tests passed.')
if __name__=='__main__':main(sys.argv[1])
