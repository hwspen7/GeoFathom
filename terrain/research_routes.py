"""Validated, cancellable experiments using the production terrain engine."""
import math
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from geometry.measure import GeometryError
from imagery.raster import RasterError
from .routes import AdvancedTerrainInput, raster, run_cancelable
from .research import analyze_experiment, SWEEP_PARAMETERS, UNCERTAINTY_OPERATIONS, SCENARIO_PARAMETERS

router = APIRouter(prefix='/terrain/research', tags=['terrain research'])

class Scenario(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=80)
    parameters: dict = Field(default_factory=dict, max_length=30)

class Experiment(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    title: str = Field(default='Terrain research experiment', min_length=1, max_length=160)
    baseline_name: str = Field(default='Baseline', min_length=1, max_length=80)
    base: AdvancedTerrainInput
    mode: Literal['comparison','sensitivity','uncertainty'] = 'comparison'
    scenarios: list[Scenario] = Field(default_factory=list, max_length=8)
    parameter: str | None = None
    values: list[float] = Field(default_factory=list, max_length=8)
    sigma_m: float = Field(default=1, gt=0, le=1000)
    samples: int = Field(default=100, ge=20, le=500)
    seed: int = Field(default=42, ge=0, le=4294967295)
    error_model: Literal['independent','common_offset'] = 'independent'
    coverage: float = Field(default=.95, ge=.5, le=.99)
    expected_source_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')

    expected_dependency_sha256: dict[str,str] = Field(default_factory=dict, max_length=4)

    @model_validator(mode='before')
    @classmethod
    def validate_base_keys(cls, data):
        if isinstance(data, dict) and isinstance(data.get('base'), dict):
            unknown = data['base'].keys() - AdvancedTerrainInput.model_fields.keys()
            if unknown:
                raise ValueError('Unknown baseline parameters: ' + ', '.join(sorted(unknown)))
        return data

    @model_validator(mode='after')
    def validate_experiment(self):
        def finite(value):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError('All experiment numbers must be finite.')
            if isinstance(value, dict):
                for item in value.values(): finite(item)
            if isinstance(value, (list,tuple)):
                for item in value: finite(item)
        finite(self.base.model_dump())
        for scenario in self.scenarios: finite(scenario.parameters)
        if any(len(checksum)!=64 or any(c not in '0123456789abcdef' for c in checksum) for checksum in self.expected_dependency_sha256.values()):
            raise ValueError('Dependency checksums must be lowercase SHA-256 values.')
        if self.base.operation not in SWEEP_PARAMETERS:
            raise ValueError('Unsupported research operation.')
        if self.mode == 'comparison':
            if not self.scenarios:
                raise ValueError('Add at least one named scenario.')
            names = [self.baseline_name.strip(), *[s.name.strip() for s in self.scenarios]]
            if any(not n for n in names) or len(set(names)) != len(names):
                raise ValueError('Use unique, nonempty scenario names.')
        if self.mode == 'sensitivity':
            if self.parameter not in SWEEP_PARAMETERS[self.base.operation]:
                raise ValueError('Choose a numeric parameter used by this operation.')
            if self.parameter == 'curvature_radius' and self.base.curvature_method != 'quadratic':
                raise ValueError('Curvature-radius sensitivity requires the quadratic method.')
            if self.parameter == 'refraction_coeff' and not self.base.consider_curvature:
                raise ValueError('Refraction sensitivity requires Earth curvature correction.')
            if len(self.values) < 2 or len(set(self.values)) != len(self.values) or not all(map(math.isfinite,self.values)):
                raise ValueError('Supply two to eight distinct finite sweep values.')
        if self.mode == 'comparison':
            for scenario in self.scenarios:
                unknown = scenario.parameters.keys() - set(SCENARIO_PARAMETERS[self.base.operation])
                if unknown:
                    raise ValueError('Unsupported parameters for this operation: ' + ', '.join(sorted(unknown)))
                if not scenario.parameters or all(getattr(self.base,k) == v for k,v in scenario.parameters.items()):
                    raise ValueError('Each scenario must change at least one algorithm parameter.')
                candidate = AdvancedTerrainInput.model_validate({**self.base.model_dump(), **scenario.parameters})
                if 'curvature_radius' in scenario.parameters and candidate.curvature_method != 'quadratic':
                    raise ValueError('Curvature radius requires the quadratic method.')
                if 'refraction_coeff' in scenario.parameters and not candidate.consider_curvature:
                    raise ValueError('Refraction coefficient requires Earth curvature correction.')
                if 'depression_method' in scenario.parameters and not candidate.fill_sinks:
                    raise ValueError('Depression method requires enabled DEM conditioning.')
        if self.mode == 'uncertainty' and self.base.external_inflow_image_id:
            raise ValueError('External inflow uncertainty requires its own joint error model.')
        if self.mode == 'uncertainty' and self.base.elevation_sigma_m != 0:
            # The outer DEM error model is the sole random input. Avoid silently
            # stacking an inner analytic earthwork error model on each trial.
            raise ValueError('Set analytic elevation sigma to zero before a Monte Carlo experiment.')
        if self.mode == 'uncertainty' and self.base.operation not in UNCERTAINTY_OPERATIONS:
            raise ValueError('Unsupported uncertainty operation.')
        return self

@router.get('/catalog')
def catalog():
    from typing import get_args
    specs = {}
    for name, field in AdvancedTerrainInput.model_fields.items():
        choices = list(get_args(field.annotation))
        if field.annotation is bool:
            choices = [True, False]
        # Only enum choices are exposed; nested tuple annotations are not UI choices.
        if not all(isinstance(value,(str,bool,int,float)) for value in choices):
            choices = []
        specs[name] = {'choices':choices, 'default':field.default if not field.is_required() else None}
    return {'parameter_specs':specs, 'sweep_parameters': SWEEP_PARAMETERS, 'uncertainty_operations': sorted(UNCERTAINTY_OPERATIONS), 'scenario_parameters': SCENARIO_PARAMETERS}

@router.post('/analyze')
async def analyze(request: Request, body: Experiment):
    try:
        return await run_cancelable(request, analyze_experiment, body, raster)
    except (RasterError, GeometryError, ValueError, OverflowError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
