#include "geometry.h"
#include <cstddef>
#include <cstdint>
#if defined(__SSE2__) || defined(_M_X64) || (defined(_M_IX86_FP) && _M_IX86_FP>=2)
#include <emmintrin.h>
#define GF_SSE2 1
#endif
namespace {
// SSE2 is guaranteed on x86-64; non-x86 platforms use the scalar path.
// The vector loads never cross the supplied range or require alignment.
std::size_t different(const unsigned char* a,const unsigned char* b,std::size_t n){
    std::size_t i=0,total=0;
#ifdef GF_SSE2
    for(;n-i>=16;i+=16){
        const auto x=_mm_loadu_si128(reinterpret_cast<const __m128i*>(a+i));
        const auto y=_mm_loadu_si128(reinterpret_cast<const __m128i*>(b+i));
        unsigned bits=static_cast<unsigned>(_mm_movemask_epi8(_mm_cmpeq_epi8(x,y)));
        // Portable 16-bit popcount; no requirement for a POPCNT instruction.
        bits=bits-((bits>>1)&0x5555U);
        bits=(bits&0x3333U)+((bits>>2)&0x3333U);
        bits=(bits+(bits>>4))&0x0f0fU;
        total+=16U-((bits+(bits>>8))&0x1fU);
    }
#endif
    for(;i<n;++i)total+=a[i]!=b[i];
    return total;
}
}
extern "C" GEOFATHOM_API int gf_mask_transitions(const unsigned char* data,
    std::size_t width,std::size_t height) noexcept {
    if(!data||!width||!height||width>16777216U/height)return -1;
    std::size_t total=0;
    for(std::size_t y=0;y<height;++y){
        const auto* row=data+y*width;
        total+=different(row,row+1,width-1);
        if(y)total+=different(row-width,row,width);
    }
    return static_cast<int>(total);
}
