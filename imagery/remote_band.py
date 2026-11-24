"""One physical calibration and validity contract for inline and tiled processing."""
import math
import numpy as np
from analysis.science_raster import require

def read_calibrated(ds,binding,quantity,window=None):
    require(1<=binding.band<=ds.count,'Selected band is outside the raster band count.')
    b=binding.band;z=ds.read(b,window=window,masked=True).astype(float).filled(np.nan)
    native_scale=float(ds.scales[b-1]);native_offset=float(ds.offsets[b-1])
    require(math.isfinite(native_scale) and math.isfinite(native_offset),'Invalid band calibration metadata.')
    tag=ds.tags(b).get('TERRAIN_UNIT') or ds.units[b-1] or ds.tags().get('TERRAIN_UNIT') or ''
    encoding=binding.encoding
    if encoding=='metadata':scale,offset=native_scale,native_offset
    elif encoding=='raw':scale,offset=1.,0.
    elif encoding=='custom':scale,offset=binding.scale,binding.offset
    else:
        require((encoding=='landsat_sr' and quantity=='reflectance') or (encoding=='landsat_st' and quantity=='kelvin'),'Landsat calibration must match the requested physical quantity.')
        require(np.all(z[np.isfinite(z)]==np.floor(z[np.isfinite(z)])) and np.all((z[np.isfinite(z)]>=0)&(z[np.isfinite(z)]<=65535)),'Landsat preset expects original unsigned integer DN.')
        scale,offset=(.0000275,-.2) if encoding=='landsat_sr' else (.00341802,149.)
        require((native_scale,native_offset)==(1.,0.) or (math.isclose(native_scale,scale,rel_tol=1e-7) and math.isclose(native_offset,offset,abs_tol=1e-7)),'Raster metadata conflicts with selected Landsat preset.')
        z[z==0]=np.nan
    require(math.isfinite(scale) and scale>0 and math.isfinite(offset),'Invalid physical calibration.')
    if quantity=='class':require(scale==1 and offset==0,'Categorical and QA bands must not be radiometrically scaled.')
    z=z*scale+offset
    require(not np.isinf(z).any(),'Band calibration overflow.')
    valid=np.isfinite(z);v=z[valid]
    require(not len(v) or np.max(abs(v))<=1e100,'Calibrated values exceed numerical range.')
    if quantity=='reflectance':require(np.all((v>=-.2-1e-9)&(v<=1.6+1e-9)),'Reflectance outside supported physical tolerance [-0.2, 1.6]; check scale, offset and product level.')
    if quantity=='class':require(np.all(v==np.floor(v)) and np.all((v>=0)&(v<=65535)),'Class codes must be integers in [0,65535].')
    if quantity in {'power','radiance'}:require(np.all(v>=0),'Linear power and radiance cannot be negative.')
    if quantity=='kelvin':require(np.all(v>0),'Kelvin temperature must be positive.')
    if quantity=='emissivity':require(np.all((v>0)&(v<=1)),'Emissivity must be in (0,1].')
    if quantity=='fraction':require(np.all((v>=0)&(v<=1)),'Fraction must be in [0,1].')
    if quantity=='transmittance':require(np.all((v>0)&(v<=1)),'Transmittance must be in (0,1].')
    if quantity=='positive_gain':require(np.all(v>0),'Calibration gain must be positive.')
    if quantity=='radiance_sd':require(np.all(v>=0),'Radiance uncertainty must be nonnegative.')
    if quantity=='fraction_sd':require(np.all((v>=0)&(v<=1)),'Fraction uncertainty must be in [0,1].')
    if quantity=='nonnegative':require(np.all(v>=0),'Standard uncertainty must be nonnegative.')
    if quantity=='slope':require(np.all((v>=0)&(v<=90)),'Slope must be in [0,90] degrees.')
    if quantity=='aspect':require(np.all((v>=0)&(v<=360)),'Aspect must be in [0,360] degrees.')
    if quantity=='wrapped_phase':require(np.all((v>=-np.pi-1e-9)&(v<=np.pi+1e-9)),'Wrapped phase must be in [-pi, pi] radians.')
    if quantity=='db':require(np.all((v>=-1000)&(v<=1000)),'Radar dB outside supported numeric range.')
    expected={'reflectance':'reflectance','class':'class','power':'linear_power','signed_power':'linear_power','wrapped_phase':'radian','db':'dB','radiance':'radiance','kelvin':'K','emissivity':'unitless','transmittance':'unitless','fraction':'unitless','positive_gain':'unitless','radiance_sd':'radiance','fraction_sd':'unitless','nonnegative':'reflectance','slope':'degree','aspect':'degree'}.get(quantity)
    unit=expected or binding.unit or tag
    if quantity=='numeric':require(bool(unit),'Declare the physical unit of each numeric band.')
    if binding.unit and expected:require(binding.unit==expected,'Declared unit conflicts with required physical quantity.')
    # Explicit role binding asserts semantics; known incompatible tagged units cannot be overridden.
    if tag and quantity!='class':
        allowed={unit}
        if quantity in {'reflectance','emissivity','power','signed_power','transmittance','fraction','fraction_sd','positive_gain','nonnegative'}:allowed|={'unitless','1','dimensionless'}
        if quantity in {'slope','aspect'}:allowed|={'degrees','deg'}
        require(tag in allowed or encoding in {'landsat_sr','landsat_st','custom'},'GeoTIFF unit conflicts with selected band quantity.')

    return z,unit,scale,offset
