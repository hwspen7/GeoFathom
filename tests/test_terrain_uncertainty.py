"""Scientific checks against closed-form truncated-Gaussian earthworks moments."""
import math

import numpy as np
import pytest

from imagery.raster import RasterError
from terrain.scientific_kernels import design_surface
from terrain.uncertainty import gaussian_earthwork_uncertainty

def oracle_moments(delta,sigma):
    p=.5*(1+math.erf(delta/(sigma*math.sqrt(2))))
    density=math.exp(-.5*(delta/sigma)**2)/math.sqrt(2*math.pi)
    ecut=delta*p+sigma*density
    efill=-delta*(1-p)+sigma*density
    varcut=(delta*delta+sigma*sigma)*p+delta*sigma*density-ecut*ecut
    varfill=(delta*delta+sigma*sigma)*(1-p)-delta*sigma*density-efill*efill
    return ecut,efill,varcut,varfill


@pytest.mark.parametrize("grid",[
 np.array([[0.]]), np.array([[-2.,0.,1.]]),
 np.array([[-3.,2.],[7.,-4.]])
])
def test_independent_earthwork_moments_agree_with_closed_form_normal_integrals(grid):
    area=7.;sigma=.8
    mask=np.ones_like(grid,bool)
    report=gaussian_earthwork_uncertainty(grid,mask,area,sigma)
    moments=[oracle_moments(float(x),sigma) for x in grid.flat]
    for key,expected in [
      ("cut_expected_m3",sum(x[0] for x in moments)*area),
      ("fill_expected_m3",sum(x[1] for x in moments)*area),
      ("cut_independent_sigma_m3",math.sqrt(sum(x[2] for x in moments))*area),
      ("fill_independent_sigma_m3",math.sqrt(sum(x[3] for x in moments))*area),
    ]:
        assert report[key]==pytest.approx(expected,abs=3e-5)
    assert report["net_independent_95pct_half_width_m3"]==pytest.approx(
        1.959963984540054*sigma*area*math.sqrt(grid.size))
    assert report["net_correlated_95pct_half_width_m3"]==pytest.approx(
        1.959963984540054*sigma*area*grid.size)


def test_correlated_quantiles_are_exact_for_common_normal_datum_shift():
    delta=np.array([[-3.,0.,2.,6.]])
    report=gaussian_earthwork_uncertainty(delta,np.ones(delta.shape,bool),1.,1.)
    z=1.959963984540054
    assert report["cut_correlated_95pct_low_m3"]==pytest.approx(
        np.maximum(delta-z,0).sum())
    assert report["cut_correlated_95pct_high_m3"]==pytest.approx(
        np.maximum(delta+z,0).sum())
    assert report["fill_correlated_95pct_low_m3"]==pytest.approx(
        np.maximum(-delta-z,0).sum())
    assert report["fill_correlated_95pct_high_m3"]==pytest.approx(
        np.maximum(-delta+z,0).sum())


def test_nodata_and_input_validation_do_not_bias_normal_volume_moments():
    delta=np.array([[0.,np.nan],[2.,-3.]])
    mask=np.isfinite(delta)
    report=gaussian_earthwork_uncertainty(delta,mask,4.,.5)
    expected=sum(oracle_moments(float(x),.5)[0] for x in delta[mask])*4.
    assert report["cut_expected_m3"]==pytest.approx(expected,abs=2e-5)
    with pytest.raises(RasterError,match="finite"):
        gaussian_earthwork_uncertainty(delta,np.ones_like(mask),4.,.5)
    with pytest.raises(RasterError,match="finite"):
        gaussian_earthwork_uncertainty(delta,mask,0.,.5)


def test_engineering_uses_uncertainty_only_when_user_supplies_sigma():
    z=np.full((3,3),105.)
    valid=np.ones_like(z,bool)
    _,no_sigma=design_surface(z,valid,1.,1.,105.)
    assert "cut_expected_m3" not in no_sigma
    _,with_sigma=design_surface(z,valid,1.,1.,105.,sigma_z=1.)
    assert with_sigma["cut_expected_m3"]>0
    assert with_sigma["fill_expected_m3"]>0
    assert with_sigma["cut_correlated_95pct_high_m3"]>with_sigma["cut_m3"]
    assert with_sigma["net_independent_95pct_half_width_m3"]>0
