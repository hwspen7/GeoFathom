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

// Segments a 4-connected region around the seed using a fixed RGB tolerance.
// Pixels are interleaved RGB888, and the destination is width * height bytes.
// Returns the number of selected pixels, or -1 on invalid inputs/failure.
// This deterministic color algorithm is not a semantic AI segmentation model.
extern "C" GEOFATHOM_API int gf_seeded_rgb_region(
    const unsigned char* rgb,
    int width, int height, int seed_x, int seed_y,
    int tolerance, unsigned char* out_mask) noexcept;
