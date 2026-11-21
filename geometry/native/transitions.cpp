#include "geometry.h"
#include <cstddef>
#include <cstdint>
#if defined(__x86_64__) || defined(_M_X64) || defined(__i386__) || defined(_M_IX86)
#define GF_X86 1
#include <immintrin.h>
#if defined(_MSC_VER)
#include <intrin.h>
#define GF_AVX2_TARGET __declspec(noinline)
#elif defined(__GNUC__) || defined(__clang__)
#define GF_AVX2_TARGET __attribute__((target("avx2"),noinline))
#endif
#endif
#if defined(__aarch64__) && (defined(__GNUC__) || defined(__clang__))
#include <arm_neon.h>
#define GF_NEON 1
#endif
namespace {
using CountFn=std::size_t(*)(const unsigned char*,const unsigned char*,std::size_t);
std::size_t scalar(const unsigned char* a,const unsigned char* b,std::size_t n){
    std::size_t total=0;
    for(std::size_t i=0;i<n;++i)total+=a[i]!=b[i];
    return total;
}
// Integer popcount without requiring the separate POPCNT ISA feature.
unsigned popcount(std::uint32_t bits){
    bits-=((bits>>1)&0x55555555U);
    bits=(bits&0x33333333U)+((bits>>2)&0x33333333U);
    bits=(bits+(bits>>4))&0x0f0f0f0fU;
    return (bits*0x01010101U)>>24;
}
#if defined(__SSE2__) || defined(_M_X64) || (defined(_M_IX86_FP) && _M_IX86_FP>=2)
#define GF_SSE2 1
std::size_t sse2(const unsigned char* a,const unsigned char* b,std::size_t n){
    std::size_t i=0,total=0;
    for(;n-i>=16;i+=16){
        const auto x=_mm_loadu_si128(reinterpret_cast<const __m128i*>(a+i));
        const auto y=_mm_loadu_si128(reinterpret_cast<const __m128i*>(b+i));
        total+=16U-popcount(static_cast<unsigned>(_mm_movemask_epi8(_mm_cmpeq_epi8(x,y))));
    }
    return total+scalar(a+i,b+i,n-i);
}
#endif
#ifdef GF_AVX2_TARGET
// Only this non-inlined function is allowed to issue AVX2 instructions.
GF_AVX2_TARGET std::size_t avx2(const unsigned char* a,const unsigned char* b,std::size_t n){
    std::size_t i=0,total=0;
    for(;n-i>=32;i+=32){
        auto x=_mm256_loadu_si256(reinterpret_cast<const __m256i*>(a+i));
        auto y=_mm256_loadu_si256(reinterpret_cast<const __m256i*>(b+i));
        total+=32U-popcount(static_cast<std::uint32_t>(_mm256_movemask_epi8(_mm256_cmpeq_epi8(x,y))));
    }
    _mm256_zeroupper();
    return total+scalar(a+i,b+i,n-i);
}
bool has_avx2(){
#if defined(_MSC_VER)
    int r[4];
    __cpuid(r,0);
    if(r[0]<7)return false;
    __cpuidex(r,1,0);
    // OSXSAVE + AVX, and OS preservation of XMM and YMM state.
    if((r[2] & ((1<<27)|(1<<28)))!=((1<<27)|(1<<28)))return false;
    if((_xgetbv(0)&6)!=6)return false;
    __cpuidex(r,7,0);
    return (r[1]&(1<<5))!=0;
#else
    __builtin_cpu_init();
    return __builtin_cpu_supports("avx2");
#endif
}
#endif
#ifdef GF_NEON
std::size_t neon(const unsigned char* a,const unsigned char* b,std::size_t n){
    std::size_t i=0,total=0;
    for(;n-i>=16;i+=16){
        auto equal=vceqq_u8(vld1q_u8(a+i),vld1q_u8(b+i));
        total+=16U-vaddvq_u8(vshrq_n_u8(equal,7));
    }
    return total+scalar(a+i,b+i,n-i);
}
#endif
unsigned available(){
    unsigned result=1; // bit 0: scalar
#ifdef GF_SSE2
    result|=2;
#endif
#ifdef GF_AVX2_TARGET
    if(has_avx2())result|=4;
#endif
#ifdef GF_NEON
    result|=8;
#endif
    return result;
}
unsigned capabilities(){static const unsigned value=available();return value;}
CountFn select(unsigned backend){
    if(backend==0){
        unsigned mask=capabilities();
        backend=(mask&4)?3:(mask&8)?4:(mask&2)?2:1;
    }
    switch(backend){
    case 1:return scalar;
#ifdef GF_SSE2
    case 2:return sse2;
#endif
#ifdef GF_AVX2_TARGET
    case 3:return (capabilities()&4)?avx2:nullptr;
#endif
#ifdef GF_NEON
    case 4:return neon;
#endif
    default:return nullptr;
    }
}
}
extern "C" GEOFATHOM_API unsigned gf_mask_transition_backends() noexcept {
    return capabilities();
}
extern "C" GEOFATHOM_API int gf_mask_transitions_backend(const unsigned char* data,
    std::size_t width,std::size_t height,unsigned backend) noexcept {
    if(!data||!width||!height||width>16777216U/height)return -1;
    auto fn=select(backend);
    if(!fn)return -1;
    std::size_t total=0;
    for(std::size_t y=0;y<height;++y){
        const auto* row=data+y*width;
        total+=fn(row,row+1,width-1);
        if(y)total+=fn(row-width,row,width);
    }
    return static_cast<int>(total);
}
extern "C" GEOFATHOM_API int gf_mask_transitions(const unsigned char* data,
    std::size_t width,std::size_t height) noexcept {
    return gf_mask_transitions_backend(data,width,height,0);
}
