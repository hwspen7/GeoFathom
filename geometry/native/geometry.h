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


// Native geometry editing kernels use a local projected XY metric coordinate
// system, not longitude/latitude degrees. These functions never allocate memory
// owned by the caller. A result of -1 means invalid input.
extern "C" {
GEOFATHOM_API int gf_snap_point(
    const double* xy, std::size_t point_count, int closed,
    double x, double y, double tolerance_m, double* out_xyz) noexcept;
GEOFATHOM_API int gf_ring_self_intersects(
    const double* xy, std::size_t point_count) noexcept;
GEOFATHOM_API int gf_simplify_line(
    const double* xy, std::size_t point_count, double tolerance_m,
    std::size_t* out_indices) noexcept;
}


// Immutable BVH spatial index of metric XY segments for high-volume queries.
// The owner must call gf_spatial_index_destroy exactly once after queries.
extern "C" {
GEOFATHOM_API void* gf_spatial_index_build(
    const double* segment_xyxy, std::size_t count) noexcept;
GEOFATHOM_API int gf_spatial_index_query(
    const void* handle, double x, double y, double tolerance_m,
    double* out_xydistance_segmentindex) noexcept;
GEOFATHOM_API void gf_spatial_index_destroy(void* handle) noexcept;
}
