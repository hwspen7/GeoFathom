"""Conservative vertical-reference metadata checks for terrain operations.

A matching declared datum name does not prove common survey control. An
unknown label is never interpreted as a known reference system.
"""
import re
from imagery.raster import RasterError


def vertical_datum(source):
    """Normalize a declared vertical datum label or return None."""
    tags={str(key).strip().upper().replace("-","_"):str(value).strip()
          for key,value in source.tags().items()}
    labels={re.sub(r"[^A-Z0-9]+","",value.upper())
            for key,value in tags.items()
            if key in {"VERTICAL_DATUM","VERTICAL_REFERENCE"} and value}
    labels.discard("")
    if len(labels)>1:
        raise RasterError("Conflicting declared DEM vertical datum labels.")
    return next(iter(labels),None)


def check_vertical_compatibility(datums):
    """Reject conflicting known references; report common declared datum."""
    known={label for label in datums if label}
    if len(known)>1:
        raise RasterError("DEM vertical datum mismatch: convert all inputs to a common vertical reference before processing.")
    return next(iter(known),None)
