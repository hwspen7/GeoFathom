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
// Batch point queries amortize Python/C++ ABI overhead for dense snapping.
// query_xy contains count interleaved metric XY pairs. outputs are count*4
// [x,y,distance,segment] records; hit_flags are count bytes (0 or 1).
// Returns number of hits, or -1 on invalid requests. No internal ownership
// escapes this function; the parent index remains immutable.
GEOFATHOM_API int gf_spatial_index_query_batch(
    const void* handle, const double* query_xy, std::size_t count,
    double tolerance_m, double* out_xydistance_segmentindex,
    unsigned char* hit_flags) noexcept;
GEOFATHOM_API void gf_spatial_index_destroy(void* handle) noexcept;
}


// Horn 3x3 terrain slope/aspect from meter-based raster cells.
// Values outside mask or containing nonfinite elevation are discarded.
// The result is [mean slope degrees, mean downhill aspect degrees or -1,
// valid interior pixels, maximum slope degrees].
extern "C" GEOFATHOM_API int gf_dem_gradient(
    const float* elevation,const unsigned char* valid,int width,int height,
    double pixel_width_m,double pixel_height_m,double* out4) noexcept;

// Contiguous float32 spectral arrays and uint8 masks. Input values must already
// be radiometrically comparable and the raster grids must be aligned by GDAL.
// Normalized difference returns valid pixel count; change returns changed count.
// Invalid pixels are set to zero and excluded from counts. A negative return
// signals invalid pointers, sizes or thresholds. Outputs need count elements.
// These kernels do not infer sensor band names or geographic coordinates.
extern "C" {
GEOFATHOM_API int gf_spectral_normalized_difference(
    const float* first, const float* second, const unsigned char* valid,
    std::size_t count, float* out_index, unsigned char* out_valid) noexcept;
GEOFATHOM_API int gf_spectral_change(
    const float* before_index, const unsigned char* before_valid,
    const float* after_index, const unsigned char* after_valid,
    std::size_t count, float threshold, unsigned char* out_class) noexcept;
}

// Bounded reusable CPU workers; the caller must destroy the handle only
// after all calls finish. Each run has disjoint output pixel ranges.
extern "C" {
GEOFATHOM_API void* gf_cpu_runtime_create(unsigned threads) noexcept;
GEOFATHOM_API void gf_cpu_runtime_destroy(void* runtime) noexcept;
GEOFATHOM_API int gf_cpu_runtime_index(void* runtime,const float* a,
    const float* b,const unsigned char* valid,std::size_t n,float* output,
    unsigned char* mask) noexcept;
GEOFATHOM_API int gf_cpu_runtime_change(void* runtime,const float* a,
    const unsigned char* av,const float* b,const unsigned char* bv,
    std::size_t n,float threshold,unsigned char* output) noexcept;
}

// Optional CUDA runtime: only exported by the CUDA-enabled library.
#ifdef GEOFATHOM_NATIVE_CUDA
extern "C" {
GEOFATHOM_API void* gf_cuda_runtime_create(std::size_t n,int device) noexcept;
GEOFATHOM_API void gf_cuda_runtime_destroy(void* g) noexcept;
GEOFATHOM_API int gf_cuda_runtime_index(void* g,const float* a,const float* b,
    const unsigned char* v,std::size_t n,float* out,unsigned char* mask) noexcept;
GEOFATHOM_API int gf_cuda_runtime_change(void* g,const float* a,const unsigned char* av,
    const float* b,const unsigned char* bv,std::size_t n,float t,unsigned char* mask) noexcept;
GEOFATHOM_API int gf_cuda_runtime_paired_change(void* handle,
    const float* old_a,const float* old_b,const unsigned char* old_v,
    const float* new_a,const float* new_b,const unsigned char* new_v,
    std::size_t n,float threshold,unsigned char* labels,unsigned char* valid) noexcept;
}
#endif

// Exact horizontal and vertical label-edge count; bounded uint8 input.
extern "C" GEOFATHOM_API int gf_mask_transitions(const unsigned char* data,
    std::size_t width,std::size_t height) noexcept;

// Explicit aligned scratch-buffer leases. Never destroy during concurrent calls.
#include <cstdint>
extern "C" {
GEOFATHOM_API void* gf_buffer_pool_create(std::size_t budget) noexcept;
GEOFATHOM_API int gf_buffer_pool_acquire(void* p,std::size_t bytes,std::uint64_t* lease,void** data) noexcept;
GEOFATHOM_API int gf_buffer_pool_release(void* p,std::uint64_t lease) noexcept;
GEOFATHOM_API int gf_buffer_pool_stats(void* p,std::size_t* out) noexcept;
GEOFATHOM_API int gf_buffer_pool_destroy(void* p) noexcept;
}

// Scalar/SSE2/AVX2/NEON capability bits; backend 0 selects automatically.
extern "C" {
GEOFATHOM_API unsigned gf_mask_transition_backends() noexcept;
GEOFATHOM_API int gf_mask_transitions_backend(const unsigned char* data,std::size_t width,std::size_t height,unsigned backend) noexcept;
}
