"""Operator-only host computing settings."""
from fastapi import APIRouter, HTTPException
from .compute_resources import ComputePolicy, ResourceBusy, resource_status, save_policy

router = APIRouter(prefix="/terrain/resources", tags=["terrain-resources"])


@router.get("")
def get_resources():
    return resource_status()


@router.put("")
def set_resources(policy: ComputePolicy):
    try:
        save_policy(policy)
    except ResourceBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return resource_status()
