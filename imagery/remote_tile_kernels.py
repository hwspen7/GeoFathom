"""Local operators used by disk processing; scientific kernels are shared."""
import numpy as np
from analysis.science_raster import require
from .remote_catalog import BY_ID,SERIES_IDS,HYPER_IDS
from .remote_kernels import optical,nd,ratio,quality_mask,lee_filter
from .remote_research import ndvi_uncertainty,surface_temperature,gamma_map,long_series
from .remote_physics import thermal_uncertainty
from .remote_inference import cloud_buffer,series_break
from .remote_temporal_models import seasonal_metrics,segmented_means
from .remote_hyperspectral import continuum_features
from .remote_satellite import gamma_change, SAR_GAMMA_IDS
from .remote_fusion import fusion,canopy

def compute(kind,v,p,times=()):
    if kind in SAR_GAMMA_IDS:return gamma_change(v,p,kind)[0]
    if kind in SERIES_IDS:
        stack=np.stack(list(v.values()))
        if kind.startswith('season_'):return seasonal_metrics(stack,times,p,kind)[0]
        if kind.startswith('segmented_'):return segmented_means(stack,times,p,kind)[0]
        if kind.startswith('series_break_'):return series_break(stack,times,p['min_segment'],kind)[0]
        return long_series(kind,stack,times,p.get('period',365))[0]
    if kind in HYPER_IDS:
        stack=np.stack(list(v.values()))
        if not np.isfinite(stack).all(axis=0).any():return np.full(stack.shape[1:],np.nan)
        return continuum_features(stack,times,kind,p)[0]
    if kind=='ndvi_uncertainty':return ndvi_uncertainty(v,p)[0]
    if BY_ID[kind].group=='Optical':return optical(kind,v,p)
    if kind=='calibrated_reflectance':return v['band']
    if kind=='ndvi_change':return nd(v['nir_after'],v['red_after'])-nd(v['nir_before'],v['red_before'])
    if kind=='dnbr':return nd(v['nir_before'],v['swir_before'])-nd(v['nir_after'],v['swir_after'])
    if kind in {'difference','relative_change','change_classes'}:
        a,b=v['before'],v['after'];d=b-a
        if kind=='difference':return d
        if kind=='relative_change':return 100*ratio(d,abs(a))
        return np.where(d>p['threshold'],2,np.where(d< -p['threshold'],1,0)).astype(float)
    if kind=='surface_temperature_rte':return surface_temperature(v,p)[0]
    if kind in {'lst_uncertainty','lst_correlated_uncertainty'}:return thermal_uncertainty(v,p)[0]
    if kind=='brightness_temperature':
        l=v['radiance'];return p['k2']/np.log1p(np.divide(p['k1'],l,out=np.full_like(l,np.nan),where=l>0))
    if kind=='temperature_celsius':return v['temperature']-273.15
    if kind=='sar_db':return 10*np.log10(np.where(v['power']>0,v['power'],np.nan))
    if kind=='sar_linear':return np.power(10,v['backscatter']/10)
    if kind=='sar_ratio':return ratio(v['cross'],v['co'])
    if kind=='dualpol_rvi':return 4*ratio(v['cross'],v['co']+v['cross'])
    if kind=='sar_log_change':
        a,b=v['before'],v['after'];return 10*(np.log10(np.where(b>0,b,np.nan))-np.log10(np.where(a>0,a,np.nan)))
    if kind=='sar_lee':return lee_filter(v['power'],p['radius'],p['enl'])
    if kind=='sar_gamma_map':return gamma_map(v['power'],p['radius'],p['enl'])[0]
    if kind=='cloud_buffer':return cloud_buffer(v['qa'],p['radius'])[0]
    if kind in {'sentinel_clear','landsat_clear','landsat_unsaturated'}:return quality_mask(v['qa'],kind)
    if kind.startswith('fusion_'):
        require(all(np.all(z[np.isfinite(z)]>0) for z in (v['first_sd'],v['second_sd'])),'Fusion standard deviations must be positive.')
        return fusion(v,p,kind)[0]
    if kind.startswith('canopy_'):return canopy(v,p,kind)[0]
    raise ValueError('Operator has no local tile kernel.')
