#include "geometry.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>
#include <new>
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
bool finite(double a) noexcept { return std::isfinite(a); }
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
        auto* index=new Index();
        index->segments.reserve(count);
        for(std::size_t i=0;i<count;++i) {
            const double ax=segment_xyxy[i*4],ay=segment_xyxy[i*4+1];
            const double bx=segment_xyxy[i*4+2],by=segment_xyxy[i*4+3];
            if(!finite(ax)||!finite(ay)||!finite(bx)||!finite(by)) {
                delete index;return nullptr;
            }
            index->segments.push_back({
                ax,ay,bx,by,std::min(ax,bx),std::min(ay,by),
                std::max(ax,bx),std::max(ay,by),(ax+bx)/2,(ay+by)/2,
            });
        }
        index->order.resize(count);
        std::iota(index->order.begin(),index->order.end(),0);
        index->nodes.reserve(count*2);
        build(*index,0,count);
        return index;
    } catch(...) {return nullptr;}
}

extern "C" GEOFATHOM_API int gf_spatial_index_query(
    const void* handle,double x,double y,double tolerance,
    double* output) noexcept {
    if(!handle || !output || !finite(x) || !finite(y) || !finite(tolerance)
       || tolerance<0) return -1;
    const Index& index=*static_cast<const Index*>(handle);
    if(index.nodes.empty()) return -1;
    double best=tolerance*tolerance, px=x,py=y;
    std::size_t found=static_cast<std::size_t>(-1);
    try {
        std::vector<int> stack{0};
        while(!stack.empty()) {
            const int node_id=stack.back();
            stack.pop_back();
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
                if(da<db) {stack.push_back(node.right);stack.push_back(node.left);}
                else {stack.push_back(node.left);stack.push_back(node.right);}
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
