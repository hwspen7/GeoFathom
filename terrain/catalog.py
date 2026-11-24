"""Scientific Terrain operation catalog: explicit capability and validation contracts.

A tool being listed is not an independent accuracy certification.
This registry is the single backend inventory used for dispatch and discovery.
"""
from collections import Counter

GROUPS = {
    "Surface": ("slope","elevation","slope_map","aspect_map","hillshade",
        "tri","tpi","curvature","plan_curvature","profile_curvature",
        "contours","distribution"),
    "Hydrology": ("flow_direction","flow_accumulation","flow_accumulation_mfd",
        "streams","stream_order","watershed"),
    "Visibility": ("visibility","viewshed_multi"),
    "Engineering": ("profile","cross_sections","volume","cutfill_map",
        "suitability","least_cost","dem_difference"),
    "3D": ("mesh",),
}
CONTROL_GROUPS = {
    "gradient": {"slope","slope_map","aspect_map","hillshade","plan_curvature",
                 "profile_curvature","suitability"},
    "classification": {"slope_map"},
    "neighborhood_radius": {"tri","tpi"},
    "sun": {"hillshade"},
    "hydrologic_conditioning": {"flow_direction","flow_accumulation",
        "flow_accumulation_mfd","streams","stream_order","watershed"},
    "mfd_convergence": {"flow_accumulation_mfd"},
    "streams_threshold": {"streams","stream_order"},
    "visibility_model": {"visibility","viewshed_multi"},
    "earthwork_reference": {"volume","cutfill_map"},
    "route_model": {"least_cost"},
    "mesh_resolution": {"mesh"},
    "line_sampling": {"profile","cross_sections"},
    "comparison_source": {"dem_difference"},
    "outlet": {"watershed"},
}
CORE_OPERATIONS = frozenset(name for group in GROUPS.values() for name in group)
ADVANCED_OPERATIONS = CORE_OPERATIONS-{"slope","profile"}


def terrain_catalog():
    if sum(map(len,GROUPS.values())) != 28 or len(CORE_OPERATIONS) != 28:
        raise RuntimeError("Terrain catalog must contain 28 distinct operations.")
    controls=Counter(name for names in CONTROL_GROUPS.values() for name in names)
    if any(name not in CORE_OPERATIONS for name in controls):
        raise RuntimeError("Terrain controls reference an unknown operation.")
    return {
        "schema_version": 1,
        "accuracy_certified": False,
        "operations": [
            {"id":name,"group":group,
             "controls":sorted(key for key,items in CONTROL_GROUPS.items() if name in items),
             "validation":"requires_independent_reference"}
            for group,names in GROUPS.items() for name in names
        ],
    }
