#pragma once

#include <cstddef>

#if defined(_WIN32)
#define GEOFATHOM_API __declspec(dllexport)
#else
#define GEOFATHOM_API __attribute__((visibility("default")))
#endif

// The input ring is [longitude, latitude, ...] in WGS84 degrees.
// The kernel is for local planar topology, NOT geodesic area computation.
// Boundary points are excluded from containment.
extern "C" {
GEOFATHOM_API int gf_contains_ring(
    const double* interleaved_xy,
    std::size_t point_count,
    double longitude,
    double latitude) noexcept;

// Intersects [west, south, east, north] bounding boxes in ordinary longitude space.
GEOFATHOM_API int gf_bbox_overlaps(
    const double* first,
    const double* second) noexcept;
}
