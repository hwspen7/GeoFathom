"""Closed request contracts for operator building experiments."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from imagery.raster import RasterError
from .building_training import TrainingOptions
from .building_research_store import dataset_path
from .semantic import _manifest


class TrainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dataset_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    training: TrainingOptions
    full_resolution: Literal[True] = True


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dataset_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_ids: list[str] = Field(min_length=2, max_length=5)
    evaluate_test: bool = False
    augmentation: Literal["none", "flips", "multiscale"] = "none"
    full_resolution: Literal[True] = True


def validate_research(kind, payload):
    request = TrainRequest.model_validate(payload) if kind == "building_train" else CompareRequest.model_validate(payload)
    try:
        dataset_path(request.dataset_id)
    except FileNotFoundError as error:
        raise RasterError("Frozen building dataset not found.") from error
    ids = [request.training.initial_model_id] if kind == "building_train" else request.model_ids
    if len(set(ids)) != len(ids):
        raise RasterError("Compare distinct building model identifiers.")
    for identifier in ids:
        if _manifest(identifier)["task"] != "building_extraction":
            raise RasterError("Building research accepts only building models.")
    return request.model_dump(mode="json")
