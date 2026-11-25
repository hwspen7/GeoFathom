"""Physical feature quantities and verifiable acquisition-time semantics."""
from datetime import datetime,timezone
from typing import Literal

import numpy as np
from pydantic import AwareDatetime,BaseModel,ConfigDict,Field

from analysis.science_raster import require

FeatureQuantity=Literal['reflectance','numeric','power','db','slope','aspect','kelvin','distance_m','fraction']

class TimeContext(BaseModel):
    model_config=ConfigDict(extra='forbid')
    time_unit:Literal['second','hour','day','year']='day'
    time_origin:AwareDatetime
    acquisition_datetimes:list[AwareDatetime]=Field(min_length=4,max_length=64)


def utc(value):
    date=value if isinstance(value,datetime) else datetime.fromisoformat(value.replace('Z','+00:00'))
    require(date.tzinfo is not None,'Acquisition timestamps require an explicit timezone.')
    return date.astimezone(timezone.utc)


def resolve_time_context(context,times,observed=()):
    observed=list(observed)
    if context is None:
        if not any(observed):return None
        require(all(observed),'Incomplete acquisition metadata; supply an explicit time context.')
        context=TimeContext(time_origin=utc(observed[0]),acquisition_datetimes=[utc(t) for t in observed])
    elif not isinstance(context,TimeContext):context=TimeContext.model_validate(context)
    dates=[utc(t) for t in context.acquisition_datetimes];origin=utc(context.time_origin)
    require(len(dates)==len(times) and all(b>a for a,b in zip(dates,dates[1:])), 'Time context must match ordered acquisitions.')
    seconds={'second':1.,'hour':3600.,'day':86400.,'year':365.25*86400.}[context.time_unit]
    actual=np.array([(t-origin).total_seconds()/seconds for t in dates])
    require(np.allclose(actual,times,atol=1e-8,rtol=1e-10),'Numeric times disagree with acquisition datetimes, origin or unit.')
    if observed:
        require(len(observed)==len(dates) and all(not value or utc(value)==date for value,date in zip(observed,dates)),
                'Declared acquisition dates conflict with source band metadata.')
    return {'time_unit':context.time_unit,'time_origin':origin.isoformat(),
        'acquisition_datetimes':[t.isoformat() for t in dates], 'year_definition':'365.25 days' if context.time_unit=='year' else None}
