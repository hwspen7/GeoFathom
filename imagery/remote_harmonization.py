"""Explicit sensor/illumination corrections and independent-support alignment checks."""
import numpy as np
from pydantic import BaseModel,ConfigDict,Field

from analysis.science_raster import require
from .remote_advanced_models import brdf
from .remote_physics import register_subpixel


class BRDFCorrection(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    f_iso:float=Field(gt=0,le=10)
    f_vol:float=Field(default=0,ge=0,le=10)
    f_geo:float=Field(default=0,ge=0,le=10)
    solar_zenith:float=Field(ge=0,le=85)
    view_zenith:float=Field(default=0,ge=0,le=75)
    relative_azimuth:float=Field(default=0,ge=0,le=360)
    target_solar_zenith:float=Field(ge=0,le=85)
    target_view_zenith:float=Field(default=0,ge=0,le=75)
    target_relative_azimuth:float=Field(default=0,ge=0,le=360)


class BandCorrection(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    gain:float=Field(default=1,gt=0,le=10)
    offset:float=Field(default=0,ge=-1,le=1)
    reference_sensor:str=Field(min_length=1,max_length=100)
    coefficient_source:str=Field(min_length=10,max_length=2000)
    brdf:BRDFCorrection|None=None


def validate_corrections(acquisitions,reference_sensor=None):
    reference_sensor=reference_sensor or acquisitions[0]['sensor']
    for acquisition in acquisitions:
        corrections=acquisition.get('corrections',{})
        require(set(corrections)<=set(acquisition['bands']),'Unknown corrected band role.')
        if acquisition['sensor']!=reference_sensor:
            require(set(corrections)==set(acquisition['bands']),'Cross-sensor acquisitions require numerical corrections for every role.')
        for item in corrections.values():
            correction=BandCorrection.model_validate(item)
            require(correction.reference_sensor==reference_sensor,'Band corrections must share the cube reference sensor.')
    return reference_sensor


def correct_band(values,spec):
    correction=BandCorrection.model_validate(spec)
    out=values.copy();evidence=correction.model_dump(mode='json')
    if correction.brdf:
        b=correction.brdf
        v={'reflectance':out,**{name:np.full(out.shape,getattr(b,name)) for name in ('f_iso','f_vol','f_geo')}}
        p={**b.model_dump(),'min_model':1e-8}
        out,meta=brdf(v,p);evidence['brdf_diagnostics']=meta
    out=out*correction.gain+correction.offset
    finite=out[np.isfinite(out)]
    require(np.all((finite>=-.2-1e-9)&(finite<=1.6+1e-9)),'Sensor harmonization exceeds supported reflectance; review coefficients.')
    return out,evidence


def registration_diagnostics(reference,candidate,mask,max_shift_pixels=.5,max_rmse=.03):
    require(np.isin(mask[np.isfinite(mask)],[0,1,2]).all(),'Registration mask uses 1 calibration, 2 independent check, 0 unused.')
    p={'max_shift':3,'min_overlap':.7,'min_correlation':.5,'peak_margin':.002}
    _,diagnostics=register_subpixel({'reference':reference,'candidate':candidate,'calibration':mask},p)
    held=(mask==2)&np.isfinite(reference)&np.isfinite(candidate)
    require(held.sum()>=16,'Registration quality requires sixteen independent check pixels.')
    rmse=float(np.sqrt(np.mean((reference[held]-candidate[held])**2)))
    shift=max(abs(diagnostics['subpixel_row_shift']),abs(diagnostics['subpixel_column_shift']))
    require(shift<=max_shift_pixels,'Acquisition requires geometric realignment before cube analysis.')
    require(rmse<=max_rmse,'Stable-reference radiometry exceeds the declared RMSE tolerance.')
    diagnostics.update(original_heldout_rmse=rmse,maximum_allowed_shift=max_shift_pixels,maximum_allowed_rmse=max_rmse,
        scope='Bounded stable-mask translation/radiometric check, not independent ground-control geolocation.')
    return diagnostics
