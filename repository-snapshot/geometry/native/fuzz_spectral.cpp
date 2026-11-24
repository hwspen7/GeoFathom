// libFuzzer mutates arbitrary float bit patterns and uint8 masks.
#include "geometry.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data,std::size_t size){
    constexpr std::size_t max=512;
    const std::size_t n=std::min(max,size/9);
    if(!n)return 0;
    std::vector<float>a(n),b(n),out(n);
    std::vector<unsigned char>valid(n),mask(n),labels(n);
    for(std::size_t i=0;i<n;++i){
        std::memcpy(&a[i],data+i*9,4);
        std::memcpy(&b[i],data+i*9+4,4);
        valid[i]=data[i*9+8];
    }
    int total=gf_spectral_normalized_difference(a.data(),b.data(),valid.data(),n,out.data(),mask.data());
    int expected=0;
    for(std::size_t i=0;i<n;++i){
        double x=a[i],y=b[i],den=x+y;
        bool ok=valid[i]&&std::isfinite(x)&&std::isfinite(y)&&std::abs(den)>1e-9;
        float ref=ok?static_cast<float>(std::clamp((x-y)/den,-1.,1.)):0.f;
        if(mask[i]!=static_cast<unsigned char>(ok)||out[i]!=ref)std::abort();
        expected+=ok;
    }
    if(total!=expected)std::abort();
    if(gf_spectral_change(out.data(),mask.data(),out.data(),mask.data(),n,.25f,labels.data())!=0)
        std::abort();
    for(auto v:labels)if(v)std::abort();
    auto width=1U+data[0]%32U;
    auto height=n/width;
    if(height){
        int edges=0;
        for(std::size_t row=0;row<height;++row)
            for(std::size_t col=0;col<width;++col){
                auto i=row*width+col;
                if(col)edges+=valid[i]!=valid[i-1];
                if(row)edges+=valid[i]!=valid[i-width];
            }
        if(gf_mask_transitions(valid.data(),width,height)!=edges)std::abort();
    }
    return 0;
}
