#include "geometry.h"

// Run C++ assertions in Release builds too; CTest must never give false greens.
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <iostream>
#include <vector>

int main() {
    // A simple square in longitude/latitude, with the closing point included.
    constexpr double ring[] = {
        0.0, 0.0, 2.0, 0.0, 2.0, 2.0, 0.0, 2.0, 0.0, 0.0
    };
    assert(gf_contains_ring(ring, 5, 1.0, 1.0) == 1);
    assert(gf_contains_ring(ring, 5, 3.0, 1.0) == 0);
    assert(gf_contains_ring(ring, 5, 0.0, 1.0) == 0);
    assert(gf_contains_ring(nullptr, 5, 1.0, 1.0) == 0);

    constexpr double a[] = {0.0, 0.0, 2.0, 2.0};
    constexpr double adjacent[] = {2.0, 1.0, 4.0, 3.0};
    constexpr double remote[] = {3.0, 3.0, 4.0, 4.0};
    assert(gf_bbox_overlaps(a, adjacent) == 1);
    assert(gf_bbox_overlaps(a, remote) == 0);
    assert(gf_bbox_overlaps(nullptr, remote) == 0);
    std::cout << "GeoFathom native geometry checks passed" << std::endl;
    // The selected 3x3 block must remain isolated from its background.
    std::vector<unsigned char> rgb(8 * 8 * 3, 0);
    for (int y = 2; y < 5; ++y) {
        for (int x = 2; x < 5; ++x) {
            const int p = 3 * (y * 8 + x);
            rgb[p] = 150;
            rgb[p + 1] = 90;
            rgb[p + 2] = 40;
        }
    }
    std::vector<unsigned char> mask(8 * 8);
    assert(gf_seeded_rgb_region(rgb.data(), 8, 8, 3, 3, 5, mask.data()) == 9);
    assert(mask[3 * 8 + 3] == 1);
    assert(mask[0] == 0);
    assert(gf_seeded_rgb_region(rgb.data(), 8, 8, -1, 3, 5, mask.data()) == -1);
    assert(gf_seeded_rgb_region(nullptr, 8, 8, 3, 3, 5, mask.data()) == -1);

    // Metric snap gives vertices precedence and finds nearest edge as needed.
    constexpr double square[] = {0,0,10,0,10,10,0,10};
    double nearest[3] = {};
    assert(gf_snap_point(square,4,1,0.1,0.2,0.5,nearest) == 1);
    assert(nearest[0] == 0.0 && nearest[1] == 0.0);
    assert(gf_snap_point(square,4,1,5.0,-0.1,0.5,nearest) == 2);
    assert(nearest[0] == 5.0 && nearest[1] == 0.0);
    assert(gf_snap_point(square,4,1,50.0,50.0,0.5,nearest) == 0);
    assert(gf_ring_self_intersects(square,4) == 0);
    constexpr double bowtie[] = {0,0,10,10,0,10,10,0};
    assert(gf_ring_self_intersects(bowtie,4) == 1);
    constexpr double polyline[] = {0,0,2,0,4,0,6,0,8,0};
    std::size_t kept[5] = {};
    assert(gf_simplify_line(polyline,5,0.01,kept) == 2);
    assert(kept[0] == 0 && kept[1] == 4);
    // RDP preserves non-collinear corners, not just endpoints.
    constexpr double zigzag[] = {0,0, 5,0, 5,5, 10,5};
    std::size_t corners[4] = {};
    assert(gf_simplify_line(zigzag,4,0.001,corners) == 4);
    assert(gf_ring_self_intersects(square,0) == -1);
    assert(gf_snap_point(square,4,1,0,0,-1,nearest) == -1);
    // The BVH must return the same nearest segment as brute force.
    constexpr double parts[] = {0,0,10,0, 10,0,10,10, 10,10,0,10, 0,10,0,0};
    void* idx=gf_spatial_index_build(parts,4);
    assert(idx);
    double out[4] = {};
    assert(gf_spatial_index_query(idx,5,0.1,1,out)==1);
    assert(out[0]==5 && out[1]==0 && out[3]==0);
    assert(gf_spatial_index_query(idx,200,200,1,out)==0);
    assert(gf_spatial_index_query(idx,5,0,-1,out)==-1);
    gf_spatial_index_destroy(idx);
    std::vector<double> many;
    for(int i=0;i<100000;++i) {
        many.push_back(i*10.0);many.push_back(0.0);
        many.push_back(i*10.0);many.push_back(100.0);
    }
    void* large=gf_spatial_index_build(many.data(),100000);
    assert(large);
    for(int q=0;q<200;++q) {
        const int i=100+q*333;
        assert(gf_spatial_index_query(large,i*10.0+0.2,44,2,out)==1);
        assert(out[3]==i);
    }
    gf_spatial_index_destroy(large);
    return 0;

