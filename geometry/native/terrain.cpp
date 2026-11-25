#include "geometry.h"
#include <algorithm>
#include <cmath>
#include <cstddef>

extern "C" GEOFATHOM_API int gf_dem_gradient(
    const float* z,const unsigned char* valid,int width,int height,
    double dx,double dy,double* result) noexcept {
    if(!z || !valid || !result || width<3 || height<3 ||
       width>2048 || height>2048 || !std::isfinite(dx) || !std::isfinite(dy) ||
       dx<=0 || dy<=0) return -1;
    double sum_slope=0,sum_sin=0,sum_cos=0,max_slope=0;
    int count=0,aspects=0;
    for(int y=1;y<height-1;++y) {
        for(int x=1;x<width-1;++x) {
            float v[9];
            bool good=true;
            for(int oy=-1;oy<=1;++oy) for(int ox=-1;ox<=1;++ox) {
                const int i=(y+oy)*width+x+ox;
                if(!valid[i] || !std::isfinite(z[i])) good=false;
                v[(oy+1)*3+ox+1]=z[i];
            }
            if(!good) continue;
            const double east=(v[2]+2*v[5]+v[8]-v[0]-2*v[3]-v[6])/(8*dx);
            const double south=(v[6]+2*v[7]+v[8]-v[0]-2*v[1]-v[2])/(8*dy);
            const double gradient=std::hypot(east,south);
            const double slope=std::atan(gradient)*180.0/3.14159265358979323846;
            max_slope=std::max(max_slope,slope);sum_slope+=slope;count++;
            if(gradient>1e-12) {
                const double azimuth=std::atan2(-east,south);
                sum_sin+=std::sin(azimuth);sum_cos+=std::cos(azimuth);
                aspects++;
            }
        }
    }
    if(count==0) return 0;
    result[0]=sum_slope/count;
    result[1]=aspects?std::fmod(std::atan2(sum_sin,sum_cos)*180.0/
                       3.14159265358979323846+360.0,360.0):-1.0;
    result[2]=static_cast<double>(count);
    result[3]=max_slope;
    return 1;
}
