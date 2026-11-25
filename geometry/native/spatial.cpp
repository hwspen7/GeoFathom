#include "geometry.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <limits>
#include <new>
#include <memory>
#include <numeric>
#include <vector>

namespace {
struct Segment { double ax,ay,bx,by,minx,miny,maxx,maxy,cx,cy; };
struct Node {
    double minx,miny,maxx,maxy;
    int left=-1,right=-1;
    std::size_t start=0,end=0;
};
struct Index {
    std::vector<Segment> segments;
    std::vector<std::size_t> order;
    std::vector<Node> nodes;
};
// Reject extreme projected coordinates that can overflow squared metric
// distances. Normal GIS coordinates are many orders below this bound.
constexpr double kMaxMetricCoordinate=1e12;
constexpr double kMaxTolerance=1e9;
bool finite_number(double a) noexcept {
    return std::isfinite(a) && std::abs(a)<=kMaxMetricCoordinate;
}
double dist_rect(double x,double y,const Node& n) noexcept {
    const double dx=x<n.minx?n.minx-x:(x>n.maxx?x-n.maxx:0.0);
    const double dy=y<n.miny?n.miny-y:(y>n.maxy?y-n.maxy:0.0);
    return dx*dx+dy*dy;
}
double nearest(double x,double y,const Segment& s,double& px,double& py) noexcept {
    const double dx=s.bx-s.ax,dy=s.by-s.ay;
    const double squared=dx*dx+dy*dy;
    const double t=squared<=0.0?0.0:std::clamp(
        ((x-s.ax)*dx+(y-s.ay)*dy)/squared,0.0,1.0);
    px=s.ax+t*dx;py=s.ay+t*dy;
    return (px-x)*(px-x)+(py-y)*(py-y);
}
int build(Index& index,std::size_t begin,std::size_t end) {
    Node node{std::numeric_limits<double>::infinity(),
        std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity()};
    node.start=begin;node.end=end;
    for(std::size_t i=begin;i<end;++i) {
        const Segment& s=index.segments[index.order[i]];
        node.minx=std::min(node.minx,s.minx);
        node.miny=std::min(node.miny,s.miny);
        node.maxx=std::max(node.maxx,s.maxx);
        node.maxy=std::max(node.maxy,s.maxy);
    }
    const int here=static_cast<int>(index.nodes.size());
    index.nodes.push_back(node);
    if(end-begin<=8) return here;
    const bool axis_x=(node.maxx-node.minx)>=(node.maxy-node.miny);
    const std::size_t mid=(begin+end)/2;
    std::nth_element(index.order.begin()+begin,index.order.begin()+mid,
        index.order.begin()+end,[&](std::size_t a,std::size_t b) {
            return axis_x?index.segments[a].cx<index.segments[b].cx:
                          index.segments[a].cy<index.segments[b].cy;
        });
    const int a=build(index,begin,mid),b=build(index,mid,end);
    index.nodes[here].left=a;index.nodes[here].right=b;
    return here;
}
}

extern "C" GEOFATHOM_API void* gf_spatial_index_build(
    const double* segment_xyxy,std::size_t count) noexcept {
    if(!segment_xyxy || count==0 || count>1000000) return nullptr;
    try {
        // Use RAII through every allocation/build failure. Returning nullptr
        // from a noexcept C ABI must never leak a partially built tree.
        auto index=std::make_unique<Index>();
        index->segments.reserve(count);
        for(std::size_t i=0;i<count;++i) {
            const double ax=segment_xyxy[i*4],ay=segment_xyxy[i*4+1];
            const double bx=segment_xyxy[i*4+2],by=segment_xyxy[i*4+3];
            if(!finite_number(ax)||!finite_number(ay)||!finite_number(bx)||!finite_number(by)) {
                return nullptr;
            }
            index->segments.push_back({
                ax,ay,bx,by,std::min(ax,bx),std::min(ay,by),
                std::max(ax,bx),std::max(ay,by),ax/2+bx/2,ay/2+by/2,
            });
        }
        index->order.resize(count);
        std::iota(index->order.begin(),index->order.end(),0);
        index->nodes.reserve(count*2);
        build(*index,0,count);
        return index.release();
    } catch(...) {return nullptr;}
}

extern "C" GEOFATHOM_API int gf_spatial_index_query(
    const void* handle,double x,double y,double tolerance,
    double* output) noexcept {
    if(!handle || !output || !finite_number(x) || !finite_number(y) ||
       !std::isfinite(tolerance) || tolerance<0 || tolerance>kMaxTolerance) return -1;
    const Index& index=*static_cast<const Index*>(handle);
    if(index.nodes.empty()) return -1;
    double best=tolerance*tolerance, px=x,py=y;
    std::size_t found=static_cast<std::size_t>(-1);
    try {
        // BVH depth is bounded by log2(1,000,000/8); avoid an allocation
        // per query and reuse the local call-frame stack for every batch item.
        std::array<int,64> stack{};
        std::size_t depth=1;
        stack[0]=0;
        while(depth!=0) {
            const int node_id=stack[--depth];
            const Node& node=index.nodes[node_id];
            if(dist_rect(x,y,node)>best) continue;
            if(node.left==-1) {
                for(std::size_t j=node.start;j<node.end;++j) {
                    const std::size_t i=index.order[j];
                    double qx=0,qy=0;
                    const double d=nearest(x,y,index.segments[i],qx,qy);
                    if(d<=best && (d<best || found==static_cast<std::size_t>(-1))) {
                        best=d;px=qx;py=qy;found=i;
                    }
                }
            } else {
                const double da=dist_rect(x,y,index.nodes[node.left]);
                const double db=dist_rect(x,y,index.nodes[node.right]);
                if(depth+2>stack.size()) return -1;
                if(da<db) {stack[depth++]=node.right;stack[depth++]=node.left;}
                else {stack[depth++]=node.left;stack[depth++]=node.right;}
            }
        }
        if(found==static_cast<std::size_t>(-1)) return 0;
        output[0]=px;output[1]=py;output[2]=std::sqrt(best);
        output[3]=static_cast<double>(found);
        return 1;
    } catch (...) {return -1;}
}
extern "C" GEOFATHOM_API void gf_spatial_index_destroy(void* handle) noexcept {
    delete static_cast<Index*>(handle);
}

// Batch queries preserve the same nearest-segment contract as single queries,
// including boundary ties and no-match flags. The owning BVH is read-only and
// may be shared by independent query threads.
extern "C" GEOFATHOM_API int gf_spatial_index_query_batch(
    const void* handle, const double* query_xy, std::size_t count,
    double tolerance, double* out_records, unsigned char* hit_flags) noexcept {
    if(!handle || !query_xy || !out_records || !hit_flags ||
       count==0 || count>1000000 || !std::isfinite(tolerance) ||
       tolerance<0 || tolerance>kMaxTolerance) return -1;
    int matched=0;
    for(std::size_t i=0; i<count; ++i) {
        const double x=query_xy[i*2],y=query_xy[i*2+1];
        if(!finite_number(x) || !finite_number(y)) return -1;
        // Initialize every record; callers never see stale output bytes.
        double* record=out_records+i*4;
        record[0]=record[1]=record[2]=record[3]=0.0;
        const int status=gf_spatial_index_query(handle,x,y,tolerance,record);
        if(status<0) return -1;
        hit_flags[i]=static_cast<unsigned char>(status==1);
        if(status==1) ++matched;
    }
    return matched;
}
