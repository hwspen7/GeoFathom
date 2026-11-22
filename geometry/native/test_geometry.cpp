#include "geometry.h"

// Run C++ assertions in Release builds too; CTest must never give false greens.
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <algorithm>
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
    // Exercise every independent input guard with valid storage for all
    // other arguments. Invalid-size calls must reject before dereferencing.
    const double inf=std::numeric_limits<double>::infinity();
    const double dnan=std::numeric_limits<double>::quiet_NaN();
    assert(gf_contains_ring(ring,2,1,1)==0);
    assert(gf_contains_ring(ring,5,inf,1)==0);
    assert(gf_contains_ring(ring,5,1,inf)==0);
    for(int coordinate=0;coordinate<8;++coordinate){
        double broken[]={0,0,2,0,2,2,0,2};
        broken[coordinate]=dnan;
        assert(gf_contains_ring(broken,4,1,1)==0);
    }
    assert(gf_bbox_overlaps(a,nullptr)==0);
    for(int coordinate=0;coordinate<4;++coordinate){
        double broken[]={0,0,2,2};
        broken[coordinate]=inf;
        assert(gf_bbox_overlaps(a,broken)==0);
        assert(gf_bbox_overlaps(broken,a)==0);
    }
    const double inverted_x[]={2,0,0,2},inverted_y[]={0,2,2,0};
    assert(gf_bbox_overlaps(inverted_x,a)==0);
    assert(gf_bbox_overlaps(inverted_y,a)==0);
    assert(gf_bbox_overlaps(a,inverted_x)==0);
    assert(gf_bbox_overlaps(a,inverted_y)==0);
    for(const double delta: {-4.,4.}){
        const double disjoint_x[]={delta,0,delta+1,2};
        const double disjoint_y[]={0,delta,2,delta+1};
        assert(gf_bbox_overlaps(a,disjoint_x)==0);
        assert(gf_bbox_overlaps(a,disjoint_y)==0);
    }
    assert(gf_seeded_rgb_region(rgb.data(),8,8,0,0,255,mask.data())==64);
    // Each RGB channel independently distinguishes a neighbor.
    for(int channel=0;channel<3;++channel){
        unsigned char tiny[]={0,0,0,0,0,0};
        tiny[3+channel]=10;
        unsigned char result[2]={};
        assert(gf_seeded_rgb_region(tiny,2,1,0,0,1,result)==1);
        assert(result[0]==1&&result[1]==0);
    }
    assert(gf_seeded_rgb_region(rgb.data(),8,8,0,0,5,nullptr)==-1);
    for(const int bad: {0,1025}){
        assert(gf_seeded_rgb_region(rgb.data(),bad,8,0,0,5,mask.data())==-1);
        assert(gf_seeded_rgb_region(rgb.data(),8,bad,0,0,5,mask.data())==-1);
    }
    assert(gf_seeded_rgb_region(rgb.data(),8,8,0,-1,5,mask.data())==-1);
    assert(gf_seeded_rgb_region(rgb.data(),8,8,8,0,5,mask.data())==-1);
    assert(gf_seeded_rgb_region(rgb.data(),8,8,0,8,5,mask.data())==-1);
    assert(gf_seeded_rgb_region(rgb.data(),8,8,0,0,-1,mask.data())==-1);
    assert(gf_seeded_rgb_region(rgb.data(),8,8,0,0,256,mask.data())==-1);

    assert(gf_snap_point(nullptr,4,1,0,0,1,nearest)==-1);
    assert(gf_snap_point(square,4,1,0,0,1,nullptr)==-1);
    assert(gf_snap_point(square,0,1,0,0,1,nearest)==-1);
    assert(gf_snap_point(square,20001,1,0,0,1,nearest)==-1);
    assert(gf_snap_point(square,4,1,inf,0,1,nearest)==-1);
    assert(gf_snap_point(square,4,1,0,inf,1,nearest)==-1);
    assert(gf_snap_point(square,4,1,0,0,dnan,nearest)==-1);
    assert(gf_snap_point(square,4,0,0,0,0,nearest)==1);
    const double malformed[]={0,0,inf,0,1,1,0,1};
    const double duplicate[]={0,0,0,0,1,1,0,1};
    assert(gf_snap_point(malformed,4,0,0,0,1,nearest)==-1);
    assert(gf_ring_self_intersects(nullptr,4)==-1);
    assert(gf_ring_self_intersects(square,4097)==-1);
    assert(gf_ring_self_intersects(malformed,4)==-1);
    assert(gf_ring_self_intersects(duplicate,4)==-1);
    assert(gf_simplify_line(nullptr,5,1,kept)==-1);
    assert(gf_simplify_line(polyline,5,1,nullptr)==-1);
    assert(gf_simplify_line(polyline,1,1,kept)==-1);
    assert(gf_simplify_line(polyline,20001,1,kept)==-1);
    assert(gf_simplify_line(polyline,5,-1,kept)==-1);
    assert(gf_simplify_line(polyline,5,dnan,kept)==-1);
    assert(gf_simplify_line(malformed,4,1,kept)==-1);

    assert(gf_spatial_index_build(nullptr,1)==nullptr);
    assert(gf_spatial_index_build(parts,0)==nullptr);
    assert(gf_spatial_index_build(parts,1000001)==nullptr);
    for(int k=0;k<4;++k){
        double bad[]={0,0,1,1};bad[k]=inf;
        assert(gf_spatial_index_build(bad,1)==nullptr);
    }
    const double degenerate[]={0,0,0,0};
    idx=gf_spatial_index_build(degenerate,1);assert(idx);
    assert(gf_spatial_index_query(idx,0,0,0,out)==1);
    assert(out[0]==0&&out[1]==0&&out[2]==0);
    assert(gf_spatial_index_query(nullptr,0,0,1,out)==-1);
    assert(gf_spatial_index_query(idx,0,0,1,nullptr)==-1);
    assert(gf_spatial_index_query(idx,0,inf,1,out)==-1);
    assert(gf_spatial_index_query(idx,0,0,dnan,out)==-1);
    assert(gf_spatial_index_query_batch(nullptr,batch_queries,3,.5,records,found_flags)==-1);
    assert(gf_spatial_index_query_batch(idx,nullptr,3,.5,records,found_flags)==-1);
    assert(gf_spatial_index_query_batch(idx,batch_queries,3,.5,nullptr,found_flags)==-1);
    assert(gf_spatial_index_query_batch(idx,batch_queries,3,.5,records,nullptr)==-1);
    assert(gf_spatial_index_query_batch(idx,batch_queries,1000001,.5,records,found_flags)==-1);
    assert(gf_spatial_index_query_batch(idx,batch_queries,3,dnan,records,found_flags)==-1);
    assert(gf_spatial_index_query_batch(idx,batch_queries,3,1e10,records,found_flags)==-1);
    const double invalid_x[]={inf,0},invalid_y[]={0,inf};
    assert(gf_spatial_index_query_batch(idx,invalid_x,1,.5,records,found_flags)==-1);
    assert(gf_spatial_index_query_batch(idx,invalid_y,1,.5,records,found_flags)==-1);
    gf_spatial_index_destroy(idx);
    gf_spatial_index_destroy(nullptr);
    // A tall BVH takes the Y-axis split; queries approach it in both directions.
    std::vector<double> vertical;
    for(int i=0;i<32;++i)
        vertical.insert(vertical.end(),{0.,i*10.,1.,i*10.});
    idx=gf_spatial_index_build(vertical.data(),32);assert(idx);
    assert(gf_spatial_index_query(idx,.5,0,1,out)==1&&out[3]==0);
    assert(gf_spatial_index_query(idx,.5,310,1,out)==1&&out[3]==31);
    gf_spatial_index_destroy(idx);

    assert(gf_dem_gradient(heights.data(),nullptr,10,10,10,10,terrain)==-1);
    assert(gf_dem_gradient(heights.data(),coverage.data(),10,10,10,10,nullptr)==-1);
    for(int bad:{2,2049}){
        assert(gf_dem_gradient(heights.data(),coverage.data(),bad,10,10,10,terrain)==-1);
        assert(gf_dem_gradient(heights.data(),coverage.data(),10,bad,10,10,terrain)==-1);
    }
    for(double bad:{0.,inf}){
        assert(gf_dem_gradient(heights.data(),coverage.data(),10,10,bad,10,terrain)==-1);
        assert(gf_dem_gradient(heights.data(),coverage.data(),10,10,10,bad,terrain)==-1);
    }
    std::fill(heights.begin(),heights.end(),100.f);
    assert(gf_dem_gradient(heights.data(),coverage.data(),10,10,10,10,terrain)==1);
    assert(terrain[0]==0&&terrain[1]==-1&&terrain[2]==64&&terrain[3]==0);
    heights[44]=nan;coverage[55]=0;
    assert(gf_dem_gradient(heights.data(),coverage.data(),10,10,10,10,terrain)==1);
    assert(terrain[2]>0&&terrain[2]<64);
    std::fill(coverage.begin(),coverage.end(),0);
    assert(gf_dem_gradient(heights.data(),coverage.data(),10,10,10,10,terrain)==0);

    assert(gf_spectral_normalized_difference(first,nullptr,valid,7,index,spectral_valid)==-1);
    assert(gf_spectral_normalized_difference(first,second,nullptr,7,index,spectral_valid)==-1);
    assert(gf_spectral_normalized_difference(first,second,valid,7,nullptr,spectral_valid)==-1);
    assert(gf_spectral_normalized_difference(first,second,valid,7,index,nullptr)==-1);
    assert(gf_spectral_normalized_difference(first,second,valid,16777217,index,spectral_valid)==-1);
    const float negative[]={-1.f,1.f,1.f};
    const float denominators[]={2.f,-2.f,nan};
    const unsigned char all[]={1,1,1};
    assert(gf_spectral_normalized_difference(negative,denominators,all,3,index,spectral_valid)==2);
    assert(index[0]==-1&&index[1]==-1&&spectral_valid[2]==0);
    assert(gf_spectral_change(nullptr,old_valid,after,new_valid,6,.2f,labels)==-1);
    assert(gf_spectral_change(before,nullptr,after,new_valid,6,.2f,labels)==-1);
    assert(gf_spectral_change(before,old_valid,nullptr,new_valid,6,.2f,labels)==-1);
    assert(gf_spectral_change(before,old_valid,after,nullptr,6,.2f,labels)==-1);
    assert(gf_spectral_change(before,old_valid,after,new_valid,6,.2f,nullptr)==-1);
    assert(gf_spectral_change(before,old_valid,after,new_valid,16777217,.2f,labels)==-1);
    assert(gf_spectral_change(before,old_valid,after,new_valid,6,nan,labels)==-1);
    assert(gf_spectral_change(before,old_valid,after,new_valid,6,1.f,labels)==-1);
    const float invalid_after[]={nan,.2f,-.2f};
    const float zero[]={0,0,0};
    assert(gf_spectral_change(zero,all,invalid_after,all,3,.2f,labels)==2);
    assert(labels[0]==0&&labels[1]==1&&labels[2]==2);
    return 0;
}
