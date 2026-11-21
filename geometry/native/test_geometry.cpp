#include "geometry.h"

// Run C++ assertions in Release builds too; CTest must never give false greens.
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <iostream>
#include <limits>
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
    assert(gf_spatial_index_query(idx,1e200,0,1,out)==-1);
    assert(gf_spatial_index_query(idx,5,0,1e100,out)==-1);
    constexpr double invalid_segments[]={1e200,0,10,0};
    assert(gf_spatial_index_build(invalid_segments,1)==nullptr);
    // Vectorized native lookups agree with scalar BVH queries.
    constexpr double batch_queries[]={5,0.1, 50,50, 10.2,5};
    double records[12]={};
    unsigned char found_flags[3]={};
    assert(gf_spatial_index_query_batch(
        idx,batch_queries,3,.5,records,found_flags)==2);
    assert(found_flags[0]==1 && found_flags[1]==0 && found_flags[2]==1);
    assert(records[3]==0 && records[11]==1);
    assert(gf_spatial_index_query_batch(
        idx,batch_queries,0,.5,records,found_flags)==-1);
    assert(gf_spatial_index_query_batch(
        idx,batch_queries,3,-.5,records,found_flags)==-1);
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
    // 10% eastward elevation grade corresponds to atan(0.1) ~ 5.71 degrees.
    std::vector<float> heights(100);
    std::vector<unsigned char> coverage(100,1);
    for(int y=0;y<10;++y) for(int x=0;x<10;++x)
        heights[y*10+x]=static_cast<float>(x);
    double terrain[4]={};
    assert(gf_dem_gradient(heights.data(),coverage.data(),10,10,10,10,terrain)==1);
    assert(terrain[0]>5.70 && terrain[0]<5.72);
    assert(terrain[2]==64);
    assert(gf_dem_gradient(nullptr,coverage.data(),10,10,10,10,terrain)==-1);
    // Nodata, NaN, and zero denominators must not create apparent targets.
    const float nan=std::numeric_limits<float>::quiet_NaN();
    const float first[]={200,100,100,0,nan,100,50};
    const float second[]={100,100,-100,0,100,100,50};
    const unsigned char valid[]={1,1,1,1,1,0,1};
    float index[7]={};
    unsigned char spectral_valid[7]={};
    const int found=gf_spectral_normalized_difference(
        first,second,valid,7,index,spectral_valid);
    assert(found==3);
    assert(index[0]>0.3333f && index[0]<0.3334f);
    assert(index[1]==0 && index[2]==0 && index[4]==0);
    assert(spectral_valid[0]==1 && spectral_valid[1]==1 &&
           spectral_valid[6]==1);
    assert(spectral_valid[2]==0 && spectral_valid[3]==0 &&
           spectral_valid[4]==0 && spectral_valid[5]==0);
    assert(gf_spectral_normalized_difference(
        nullptr,second,valid,7,index,spectral_valid)==-1);
    assert(gf_spectral_normalized_difference(
        first,second,valid,0,index,spectral_valid)==-1);

    // Change classification is signed and excludes invalid source pixels.
    const float before[]={0,0,0,0,nan,0};
    const float after[]={.5f,-.6f,.1f,-.9f,.9f,.8f};
    const unsigned char old_valid[]={1,1,1,0,1,1};
    const unsigned char new_valid[]={1,1,1,1,1,0};
    unsigned char labels[6]={255,255,255,255,255,255};
    assert(gf_spectral_change(before,old_valid,after,new_valid,
                              6,.2f,labels)==2);
    assert(labels[0]==1 && labels[1]==2 && labels[2]==0 &&
           labels[3]==0 && labels[4]==0 && labels[5]==0);
    assert(gf_spectral_change(before,old_valid,after,new_valid,
                              6,-.1f,labels)==-1);
    assert(gf_spectral_change(before,old_valid,after,new_valid,
                              0,.2f,labels)==-1);
    return 0;
}
