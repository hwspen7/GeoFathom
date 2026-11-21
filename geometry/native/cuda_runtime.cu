#include "geometry.h"
#include <cuda_runtime.h>
#include <cmath>
#include <mutex>
#include <new>

namespace {
constexpr std::size_t max_pixels=16U*1024U*1024U;
// One explicit owner keeps device buffers resident between calls.
struct GPU {
    std::size_t capacity=0;
    int device=0;
    float *a=nullptr,*b=nullptr,*out=nullptr;
    unsigned char *av=nullptr,*bv=nullptr,*mask=nullptr;
    std::mutex lock;
    ~GPU(){
        cudaSetDevice(device);
        cudaFree(mask);cudaFree(bv);cudaFree(av);
        cudaFree(out);cudaFree(b);cudaFree(a);
    }
    bool initialize(){
        return cudaSetDevice(device)==cudaSuccess &&
            cudaMalloc(reinterpret_cast<void**>(&a),capacity*sizeof(float))==cudaSuccess &&
            cudaMalloc(reinterpret_cast<void**>(&b),capacity*sizeof(float))==cudaSuccess &&
            cudaMalloc(reinterpret_cast<void**>(&out),capacity*sizeof(float))==cudaSuccess &&
            cudaMalloc(reinterpret_cast<void**>(&av),capacity)==cudaSuccess &&
            cudaMalloc(reinterpret_cast<void**>(&bv),capacity)==cudaSuccess &&
            cudaMalloc(reinterpret_cast<void**>(&mask),capacity)==cudaSuccess;
    }
};
__global__ void nd(const float* a,const float* b,const unsigned char* valid,
                   std::size_t n,float* out,unsigned char* mask){
    const std::size_t i=blockIdx.x*blockDim.x+threadIdx.x;
    if(i>=n)return;
    out[i]=0;mask[i]=0;
    if(!valid[i]||!isfinite(a[i])||!isfinite(b[i]))return;
    const double x=a[i],y=b[i],d=x+y;
    if(!isfinite(d)||fabs(d)<=1e-9)return;
    const double v=(x-y)/d;
    if(!isfinite(v))return;
    out[i]=static_cast<float>(fmin(1.0,fmax(-1.0,v)));
    mask[i]=1;
}
__global__ void change(const float* a,const unsigned char* av,
    const float* b,const unsigned char* bv,std::size_t n,float t,unsigned char* mask){
    const std::size_t i=blockIdx.x*blockDim.x+threadIdx.x;
    if(i>=n)return;
    mask[i]=0;
    if(!av[i]||!bv[i]||!isfinite(a[i])||!isfinite(b[i]))return;
    const double delta=static_cast<double>(b[i])-static_cast<double>(a[i]);
    if(delta>=t)mask[i]=1;
    else if(delta<=-t)mask[i]=2;
}
// The first normalized index and validity remain resident while the second
// date is uploaded. Round the second index to float32 exactly as the
// standalone kernel does, so threshold decisions agree with the scalar API.
__global__ void paired(const float* prior,const unsigned char* prior_valid,
    const float* a,const float* b,const unsigned char* valid,std::size_t n,
    float threshold,unsigned char* labels,unsigned char* both){
    const std::size_t i=blockIdx.x*blockDim.x+threadIdx.x;
    if(i>=n)return;
    const bool usable=prior_valid[i]&&valid[i];
    labels[i]=0;both[i]=0;
    if(!usable||!isfinite(a[i])||!isfinite(b[i]))return;
    double x=a[i],y=b[i],den=x+y;
    if(!isfinite(den)||fabs(den)<=1e-9)return;
    double v=(x-y)/den;
    if(!isfinite(v))return;
    float next=static_cast<float>(fmin(1.0,fmax(-1.0,v)));
    double delta=static_cast<double>(next)-prior[i];
    both[i]=1;
    if(delta>=threshold)labels[i]=1;
    else if(delta<=-threshold)labels[i]=2;
}
bool upload(GPU& g,const float* a,const float* b,const unsigned char* v,std::size_t n){
    return cudaSetDevice(g.device)==cudaSuccess &&
      cudaMemcpy(g.a,a,n*sizeof(float),cudaMemcpyHostToDevice)==cudaSuccess &&
      cudaMemcpy(g.b,b,n*sizeof(float),cudaMemcpyHostToDevice)==cudaSuccess &&
      cudaMemcpy(g.av,v,n,cudaMemcpyHostToDevice)==cudaSuccess;
}
}
extern "C" GEOFATHOM_API void* gf_cuda_runtime_create(std::size_t n,int device) noexcept {
    if(!n||n>max_pixels||device<0)return nullptr;
    try{
        auto g=new GPU;
        g->device=device;g->capacity=n;
        if(!g->initialize()){delete g;return nullptr;}
        return g;
    }catch(...){return nullptr;}
}
extern "C" GEOFATHOM_API void gf_cuda_runtime_destroy(void* g) noexcept {
    delete static_cast<GPU*>(g);
}
extern "C" GEOFATHOM_API int gf_cuda_runtime_index(void* handle,
    const float* a,const float* b,const unsigned char* valid,std::size_t n,
    float* result,unsigned char* mask) noexcept {
    if(!handle||!a||!b||!valid||!result||!mask||!n)return -1;
    auto& g=*static_cast<GPU*>(handle);
    if(n>g.capacity)return -1;
    try{
        std::lock_guard<std::mutex> guard(g.lock);
        if(!upload(g,a,b,valid,n))return -1;
        nd<<<static_cast<unsigned>((n+255)/256),256>>>(g.a,g.b,g.av,n,g.out,g.mask);
        if(cudaGetLastError()!=cudaSuccess||cudaDeviceSynchronize()!=cudaSuccess)return -1;
        if(cudaMemcpy(result,g.out,n*sizeof(float),cudaMemcpyDeviceToHost)!=cudaSuccess||
           cudaMemcpy(mask,g.mask,n,cudaMemcpyDeviceToHost)!=cudaSuccess)return -1;
        int count=0;for(std::size_t i=0;i<n;++i)count+=mask[i]!=0;
        return count;
    }catch(...){return -1;}
}
extern "C" GEOFATHOM_API int gf_cuda_runtime_change(void* handle,
    const float* a,const unsigned char* av,const float* b,const unsigned char* bv,
    std::size_t n,float threshold,unsigned char* mask) noexcept {
    if(!handle||!a||!b||!av||!bv||!mask||!n||
       !std::isfinite(threshold)||threshold<=0||threshold>=1)return -1;
    auto& g=*static_cast<GPU*>(handle);
    if(n>g.capacity)return -1;
    try{
        std::lock_guard<std::mutex> guard(g.lock);
        if(!upload(g,a,b,av,n)||cudaMemcpy(g.bv,bv,n,cudaMemcpyHostToDevice)!=cudaSuccess)return -1;
        change<<<static_cast<unsigned>((n+255)/256),256>>>(g.a,g.av,g.b,g.bv,n,threshold,g.mask);
        if(cudaGetLastError()!=cudaSuccess||cudaDeviceSynchronize()!=cudaSuccess||
           cudaMemcpy(mask,g.mask,n,cudaMemcpyDeviceToHost)!=cudaSuccess)return -1;
        int count=0;for(std::size_t i=0;i<n;++i)count+=mask[i]!=0;
        return count;
    }catch(...){return -1;}
}

extern "C" GEOFATHOM_API int gf_cuda_runtime_paired_change(void* handle,
    const float* old_a,const float* old_b,const unsigned char* old_v,
    const float* new_a,const float* new_b,const unsigned char* new_v,
    std::size_t n,float threshold,unsigned char* labels,unsigned char* valid) noexcept{
    if(!handle||!old_a||!old_b||!old_v||!new_a||!new_b||!new_v||!labels||!valid||
       !n||!std::isfinite(threshold)||threshold<=0||threshold>=1)return -1;
    auto& g=*static_cast<GPU*>(handle);
    if(n>g.capacity)return -1;
    try{
        std::lock_guard<std::mutex> guard(g.lock);
        if(!upload(g,old_a,old_b,old_v,n))return -1;
        nd<<<static_cast<unsigned>((n+255)/256),256>>>(g.a,g.b,g.av,n,g.out,g.bv);
        if(cudaGetLastError()!=cudaSuccess||cudaDeviceSynchronize()!=cudaSuccess)return -1;
        if(!upload(g,new_a,new_b,new_v,n))return -1;
        // g.av is the second-date input validity. Reuse it as the overlap
        // output only after its value has been read by each independent thread.
        // Use g.mask for final labels and return both byte masks to the host.
        paired<<<static_cast<unsigned>((n+255)/256),256>>>(g.out,g.bv,g.a,g.b,g.av,n,
            threshold,g.mask,g.av);
        if(cudaGetLastError()!=cudaSuccess||cudaDeviceSynchronize()!=cudaSuccess||
           cudaMemcpy(labels,g.mask,n,cudaMemcpyDeviceToHost)!=cudaSuccess||
           cudaMemcpy(valid,g.av,n,cudaMemcpyDeviceToHost)!=cudaSuccess)return -1;
        int count=0;for(std::size_t i=0;i<n;++i)count+=valid[i]!=0;
        return count;
    }catch(...){return -1;}
}
