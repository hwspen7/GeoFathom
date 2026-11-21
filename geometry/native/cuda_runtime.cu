#include "geometry.h"
#include <cuda_runtime.h>
#include <cmath>
#include <algorithm>
#include <mutex>
#include <new>

namespace {
constexpr std::size_t max_pixels=16U*1024U*1024U;
// One explicit owner keeps device buffers resident between calls.
struct GPU {
    std::size_t limit=0,capacity=0;
    int device=0;
    float *a=nullptr,*b=nullptr,*out=nullptr;
    unsigned char *av=nullptr,*bv=nullptr,*mask=nullptr;
    std::mutex lock;
    void release() noexcept {
        cudaFree(mask);cudaFree(bv);cudaFree(av);
        cudaFree(out);cudaFree(b);cudaFree(a);
        mask=bv=av=nullptr;out=b=a=nullptr;capacity=0;
    }
    ~GPU(){if(cudaSetDevice(device)==cudaSuccess)release();}
    bool ensure(std::size_t requested){
        if(requested>limit||cudaSetDevice(device)!=cudaSuccess)return false;
        if(requested<=capacity)return true;
        // All previous calls synchronize before returning. Free the idle
        // allocation first to avoid a transient old+new allocation peak.
        release();
        std::size_t target=std::min(limit,std::max(requested,std::size_t(65536)));
        // Round to a reusable power of two, bounded by the configured limit.
        std::size_t rounded=1;
        while(rounded<target)rounded*=2;
        target=std::min(rounded,limit);
        std::size_t free=0,total=0;
        if(cudaMemGetInfo(&free,&total)!=cudaSuccess)return false;
        constexpr std::size_t bytes_per_pixel=3*sizeof(float)+3;
        if(target>free/bytes_per_pixel)return false;
        bool ok=cudaMalloc(reinterpret_cast<void**>(&a),target*sizeof(float))==cudaSuccess &&
            cudaMalloc(reinterpret_cast<void**>(&b),target*sizeof(float))==cudaSuccess &&
            cudaMalloc(reinterpret_cast<void**>(&out),target*sizeof(float))==cudaSuccess &&
            cudaMalloc(reinterpret_cast<void**>(&av),target)==cudaSuccess &&
            cudaMalloc(reinterpret_cast<void**>(&bv),target)==cudaSuccess &&
            cudaMalloc(reinterpret_cast<void**>(&mask),target)==cudaSuccess;
        if(!ok){release();return false;}
        capacity=target;
        return true;
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
        g->device=device;g->limit=n;
        if(cudaSetDevice(device)!=cudaSuccess){delete g;return nullptr;}
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
    try{
        std::lock_guard<std::mutex> guard(g.lock);
        if(!g.ensure(n))return -1;
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
    try{
        std::lock_guard<std::mutex> guard(g.lock);
        if(!g.ensure(n))return -1;
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
    try{
        std::lock_guard<std::mutex> guard(g.lock);
        if(!g.ensure(n))return -1;
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

// Operator-owned device arrays: no host copies, no internal scratch buffers.
// Caller must provide non-overlapping, contiguous buffers of at least n
// elements, all on the current CUDA device, and keep them alive until return.
namespace {
bool device_pointer(const void* p,int device){
    cudaPointerAttributes a{};
    return p&&cudaPointerGetAttributes(&a,p)==cudaSuccess&&
        a.type==cudaMemoryTypeDevice&&a.device==device;
}
}
extern "C" GEOFATHOM_API int gf_cuda_device_index(int device,const float* a,
    const float* b,const unsigned char* valid,std::size_t n,
    float* out,unsigned char* mask) noexcept {
    if(!n||n>max_pixels||device<0||cudaSetDevice(device)!=cudaSuccess)return -1;
    if(!device_pointer(a,device)||!device_pointer(b,device)||
       !device_pointer(valid,device)||!device_pointer(out,device)||
       !device_pointer(mask,device))return -1;
    // Synchronize upstream producer streams before using their buffers.
    if(cudaDeviceSynchronize()!=cudaSuccess)return -1;
    nd<<<static_cast<unsigned>((n+255)/256),256>>>(a,b,valid,n,out,mask);
    return cudaGetLastError()==cudaSuccess&&cudaDeviceSynchronize()==cudaSuccess?0:-1;
}
extern "C" GEOFATHOM_API int gf_cuda_device_change(int device,const float* a,
    const unsigned char* av,const float* b,const unsigned char* bv,std::size_t n,
    float threshold,unsigned char* mask) noexcept {
    if(!n||n>max_pixels||!std::isfinite(threshold)||threshold<=0||threshold>=1||
       device<0||cudaSetDevice(device)!=cudaSuccess)return -1;
    if(!device_pointer(a,device)||!device_pointer(av,device)||
       !device_pointer(b,device)||!device_pointer(bv,device)||!device_pointer(mask,device))return -1;
    if(cudaDeviceSynchronize()!=cudaSuccess)return -1;
    change<<<static_cast<unsigned>((n+255)/256),256>>>(a,av,b,bv,n,threshold,mask);
    return cudaGetLastError()==cudaSuccess&&cudaDeviceSynchronize()==cudaSuccess?0:-1;
}
extern "C" GEOFATHOM_API int gf_cuda_runtime_stats(void* handle,std::size_t* out) noexcept {
    if(!handle||!out)return -1;
    try{
        auto& g=*static_cast<GPU*>(handle);
        std::lock_guard<std::mutex> guard(g.lock);
        out[0]=g.capacity;out[1]=g.limit;out[2]=g.capacity*(3*sizeof(float)+3);
        return 0;
    }catch(...){return -1;}
}
extern "C" GEOFATHOM_API int gf_cuda_runtime_trim(void* handle) noexcept {
    if(!handle)return -1;
    try{
        auto& g=*static_cast<GPU*>(handle);
        std::lock_guard<std::mutex> guard(g.lock);
        if(cudaSetDevice(g.device)!=cudaSuccess||cudaDeviceSynchronize()!=cudaSuccess)return -1;
        g.release();return 0;
    }catch(...){return -1;}
}
