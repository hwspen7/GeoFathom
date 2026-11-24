"""Analytic Gaussian cut/fill uncertainty: no Monte Carlo sampling or seed drift.

The input sigma is an explicitly assumed independent normal vertical error
per valid cell. A second, fully correlated datum-offset scenario is reported
separately; no probabilistic statement is made about an unknown error model.
The deterministic cut/fill result itself is never replaced by an expectation.
"""
import math

import numpy as np

from imagery.raster import RasterError
from .cancellation import checkpoint

_Z95=1.959963984540054
_SQRT2PI=math.sqrt(2*math.pi)


def _normal_cdf_positive(x):
    """Bounded, vectorized A&S 7.1.26 CDF; max absolute error ~7.5e-8."""
    t=1/(1+.2316419*x)
    pdf=np.exp(-.5*x*x)/_SQRT2PI
    polynomial=((((1.330274429*t-1.821255978)*t+1.781477937)*t-
                 .356563782)*t+.319381530)*t
    return 1-pdf*polynomial,pdf


def gaussian_earthwork_uncertainty(difference,valid,cell_area_m2,sigma_m,cancel=None):
    """Return named 95% approximate normal/fully-correlated volume bounds.

    The independent-cell cut/fill bounds use normal approximations to sums
    of rectified Gaussian variables; the independent net volume is exactly
    normal under the stated model. Correlated bounds correspond to a single
    common Gaussian vertical offset over the entire valid area.
    """
    diff=np.asarray(difference,dtype=np.float64)
    valid=np.asarray(valid,dtype=bool)
    if (diff.ndim!=2 or diff.shape!=valid.shape or not valid.any() or
        not np.isfinite(diff[valid]).all() or not math.isfinite(cell_area_m2) or
        cell_area_m2<=0 or not math.isfinite(sigma_m) or sigma_m<=0):
        raise RasterError("Gaussian earthwork uncertainty requires a finite assumed sigma, metric cell area and valid differences.")
    n=int(valid.sum())
    expected_cut=expected_fill=second_cut=second_fill=0.
    lo_cut=hi_cut=lo_fill=hi_fill=0.
    sigma=sigma_m
    for row in range(0,diff.shape[0],64):
        checkpoint(cancel)
        mask=valid[row:row+64]
        d=diff[row:row+64][mask]
        if not d.size:continue
        x=d/sigma
        cdf_positive,pdf=_normal_cdf_positive(np.abs(x))
        phi=np.where(x>=0,cdf_positive,1-cdf_positive)
        pdf=np.asarray(pdf,dtype=np.float64)
        cut=sigma*pdf+d*phi
        fill=sigma*pdf-d*(1-phi)
        c2=(d*d+sigma*sigma)*phi+d*sigma*pdf
        f2=(d*d+sigma*sigma)*(1-phi)-d*sigma*pdf
        expected_cut+=float(cut.sum())
        expected_fill+=float(fill.sum())
        second_cut+=float(np.maximum(0,c2-cut*cut).sum())
        second_fill+=float(np.maximum(0,f2-fill*fill).sum())
        lo_cut+=float(np.maximum(d-_Z95*sigma,0).sum())
        hi_cut+=float(np.maximum(d+_Z95*sigma,0).sum())
        lo_fill+=float(np.maximum(-d-_Z95*sigma,0).sum())
        hi_fill+=float(np.maximum(-d+_Z95*sigma,0).sum())
    area=cell_area_m2
    cut_mean=expected_cut*area;fill_mean=expected_fill*area
    cut_sd=math.sqrt(second_cut)*area;fill_sd=math.sqrt(second_fill)*area
    net_sd_independent=sigma*area*math.sqrt(n)
    net_sd_correlated=sigma*area*n
    return {
        "uncertainty_model_gaussian_assumed":1,
        "cut_expected_m3":cut_mean,
        "fill_expected_m3":fill_mean,
        "cut_independent_sigma_m3":cut_sd,
        "fill_independent_sigma_m3":fill_sd,
        "cut_independent_95pct_low_m3":max(0,cut_mean-_Z95*cut_sd),
        "cut_independent_95pct_high_m3":cut_mean+_Z95*cut_sd,
        "fill_independent_95pct_low_m3":max(0,fill_mean-_Z95*fill_sd),
        "fill_independent_95pct_high_m3":fill_mean+_Z95*fill_sd,
        "cut_correlated_95pct_low_m3":lo_cut*area,
        "cut_correlated_95pct_high_m3":hi_cut*area,
        "fill_correlated_95pct_low_m3":lo_fill*area,
        "fill_correlated_95pct_high_m3":hi_fill*area,
        "net_independent_95pct_half_width_m3":_Z95*net_sd_independent,
        "net_correlated_95pct_half_width_m3":_Z95*net_sd_correlated,
    }
