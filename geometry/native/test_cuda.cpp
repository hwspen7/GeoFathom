#include "geometry.h"
#include <cmath>
#include <cuda_runtime.h>
#include <vector>
#include <limits>
#include <random>
#include <algorithm>
int main(){
    constexpr std::size_t n=65539;
    std::vector<float>a(n,200),b(n,50),x(n),y(n);
    std::vector<unsigned char> v(n,1),xm(n),ym(n),cl(n);
    a[0]=std::numeric_limits<float>::quiet_NaN();v[n-1]=0;
    void* gpu=gf_cuda_runtime_create(n,0);
    if(!gpu)return 1;
    const int expected=gf_spectral_normalized_difference(a.data(),b.data(),v.data(),n,x.data(),xm.data());
    for(int j=0;j<10;++j){
        if(gf_cuda_runtime_index(gpu,a.data(),b.data(),v.data(),n,y.data(),ym.data())!=expected||xm!=ym)return 2;
        for(std::size_t i=0;i<n;++i)if(std::abs(x[i]-y[i])>1e-6f)return 3;
    }
    if(gf_cuda_runtime_change(gpu,x.data(),xm.data(),y.data(),ym.data(),n,.2f,cl.data())!=0)return 4;
    std::vector<float> newer(n,400),new_index(n);
    std::vector<unsigned char> new_mask(n),reference(n),both(n);
    gf_spectral_normalized_difference(newer.data(),b.data(),v.data(),n,new_index.data(),new_mask.data());
    gf_spectral_change(x.data(),xm.data(),new_index.data(),new_mask.data(),n,.1f,reference.data());
    if(gf_cuda_runtime_paired_change(gpu,a.data(),b.data(),v.data(),newer.data(),
        b.data(),v.data(),n,.1f,cl.data(),both.data())<0||cl!=reference)return 5;
    for(std::size_t i=0;i<n;++i)if(both[i]!=(xm[i]&&new_mask[i]))return 6;
    std::size_t stats[3]{};
    if(gf_cuda_runtime_stats(gpu,stats)||stats[0]<n||stats[1]!=n||stats[2]!=stats[0]*15)return 7;
    if(gf_cuda_runtime_trim(gpu)||gf_cuda_runtime_stats(gpu,stats)||stats[0])return 8;
    if(gf_cuda_runtime_index(gpu,a.data(),b.data(),v.data(),n,y.data(),ym.data())!=expected)return 9;
    // Actual device array API: both operations use the same device buffers.
    float *da=nullptr,*db=nullptr,*dx=nullptr,*dy=nullptr;
    unsigned char *dv=nullptr,*mx=nullptr,*my=nullptr,*dl=nullptr;
    if(cudaMalloc(reinterpret_cast<void**>(&da),n*4)!=cudaSuccess||
       cudaMalloc(reinterpret_cast<void**>(&db),n*4)!=cudaSuccess||
       cudaMalloc(reinterpret_cast<void**>(&dx),n*4)!=cudaSuccess||
       cudaMalloc(reinterpret_cast<void**>(&dy),n*4)!=cudaSuccess||
       cudaMalloc(reinterpret_cast<void**>(&dv),n)!=cudaSuccess||
       cudaMalloc(reinterpret_cast<void**>(&mx),n)!=cudaSuccess||
       cudaMalloc(reinterpret_cast<void**>(&my),n)!=cudaSuccess||
       cudaMalloc(reinterpret_cast<void**>(&dl),n)!=cudaSuccess)return 10;
    if(cudaMemcpy(da,a.data(),n*4,cudaMemcpyHostToDevice)!=cudaSuccess||
       cudaMemcpy(db,b.data(),n*4,cudaMemcpyHostToDevice)!=cudaSuccess||
       cudaMemcpy(dv,v.data(),n,cudaMemcpyHostToDevice)!=cudaSuccess)return 11;
    if(gf_cuda_device_index(0,da,db,dv,n,dx,mx))return 12;
    if(gf_cuda_device_index(0,db,da,dv,n,dy,my))return 13;
    if(gf_cuda_device_change(0,dx,mx,dy,my,n,.1f,dl))return 14;
    if(cudaMemcpy(cl.data(),dl,n,cudaMemcpyDeviceToHost)!=cudaSuccess)return 15;
    for(std::size_t i=0;i<n;++i)if(cl[i]!=(xm[i]?2:0))return 16;
    // Native semantic postprocessing checks NCHW layout, ties and invalid logits.
    constexpr std::size_t pixels=5,batch=2,classes=3;
    std::vector<float> logits(batch*pixels*classes,0.f);
    for(std::size_t i=0;i<pixels;++i){logits[pixels+i]=2.f;logits[4*pixels+i]=-2.f;}
    logits[0]=std::numeric_limits<float>::quiet_NaN();
    if(cudaMemcpy(da,logits.data(),logits.size()*sizeof(float),cudaMemcpyHostToDevice)!=cudaSuccess)return 17;
    if(gf_cuda_device_semantic(0,da,batch,pixels,classes,0,dl,dx))return 18;
    std::vector<float> confidence(batch*pixels);
    if(cudaMemcpy(cl.data(),dl,batch*pixels,cudaMemcpyDeviceToHost)!=cudaSuccess||
       cudaMemcpy(confidence.data(),dx,batch*pixels*sizeof(float),cudaMemcpyDeviceToHost)!=cudaSuccess)return 19;
    if(!std::isnan(confidence[0]))return 20;
    for(std::size_t i=1;i<pixels;++i)
        if(cl[i]!=1||std::abs(confidence[i]-1.f/(1.f+2.f*std::exp(-2.f)))>1e-6f)return 21;
    for(std::size_t i=pixels;i<batch*pixels;++i)
        if(cl[i]!=0||std::abs(confidence[i]-1.f/(2.f+std::exp(-2.f)))>1e-6f)return 22;
    cudaFree(da);cudaFree(db);cudaFree(dx);cudaFree(dy);cudaFree(dv);
    cudaFree(mx);cudaFree(my);cudaFree(dl);
    // Differential acceptance: seeded adverse values, odd tile sizes,
    // reusable allocations, exact masks and labels, threshold boundaries.
    std::mt19937 rng(3567);
    std::uniform_real_distribution<float> distribution(-1000.f,1000.f);
    for(const std::size_t count: {std::size_t(1),std::size_t(31),std::size_t(257),
                                 std::size_t(4099),n}){
        for(std::size_t i=0;i<count;++i){
            a[i]=distribution(rng); b[i]=distribution(rng);
            newer[i]=distribution(rng);
            v[i]=static_cast<unsigned char>(rng()%5!=0);
        }
        a[0]=std::numeric_limits<float>::quiet_NaN();
        if(count>7){
            a[1]=std::numeric_limits<float>::infinity();
            a[2]=b[2]=std::numeric_limits<float>::max();
            a[3]=1e-10f; b[3]=-1e-10f;
            a[4]=0.f; b[4]=0.f;
            a[5]=3.f; b[5]=1.f; newer[5]=1.f;
            a[6]=-3.f; b[6]=1.f;
            v[1]=v[2]=v[3]=v[4]=v[5]=v[6]=1;
        }
        const int cpu=gf_spectral_normalized_difference(a.data(),b.data(),v.data(),count,x.data(),xm.data());
        const int cuda=gf_cuda_runtime_index(gpu,a.data(),b.data(),v.data(),count,y.data(),ym.data());
        if(cpu!=cuda||!std::equal(xm.begin(),xm.begin()+count,ym.begin()))return 23;
        for(std::size_t i=0;i<count;++i)
            if(!std::isfinite(y[i])||std::abs(x[i]-y[i])>1e-6f)return 24;
        gf_spectral_normalized_difference(newer.data(),b.data(),v.data(),count,new_index.data(),new_mask.data());
        if(gf_spectral_change(x.data(),xm.data(),new_index.data(),new_mask.data(),count,.25f,reference.data())<0)return 25;
        // Fused ABI returns jointly valid pixels, not the number of changes.
        const int cuda_valid=gf_cuda_runtime_paired_change(gpu,a.data(),b.data(),v.data(),newer.data(),
            b.data(),v.data(),count,.25f,cl.data(),both.data());
        if(cuda_valid<0||!std::equal(reference.begin(),reference.begin()+count,cl.begin()))return 25;
        int joint_valid=0;
        for(std::size_t i=0;i<count;++i){
            const bool valid=xm[i]&&new_mask[i];
            if(both[i]!=valid)return 26;
            joint_valid+=valid;
        }
        if(cuda_valid!=joint_valid)return 26;
        if(gf_cuda_runtime_stats(gpu,stats)||stats[0]<count||stats[0]>n||stats[2]!=stats[0]*15)return 27;
        if(gf_cuda_runtime_trim(gpu)||gf_cuda_runtime_stats(gpu,stats)||stats[0]||stats[2])return 28;
    }
    // Physical-device parity for both gradient methods, including NoData halo.
    constexpr int w=67,h=71;
    std::vector<float> dem(w*h),east(w*h),south(w*h);
    std::vector<unsigned char> mask(w*h,1),valid(w*h);
    for(int r=0;r<h;++r)for(int c=0;c<w;++c)dem[r*w+c]=100.f+3.f*c-2.f*r;
    mask[20*w+20]=0;
    std::size_t terrain_memory[2]{};
    if(gf_cuda_terrain_memory(0,terrain_memory)||!terrain_memory[1])return 29;
    for(int method=0;method<2;++method){
        if(gf_cuda_terrain_gradient(0,dem.data(),mask.data(),w,h,10.,20.,method,1024*1024,
                                    east.data(),south.data(),valid.data()))return 30;
        for(int r=0;r<h;++r)for(int c=0;c<w;++c){
            const bool expected=r>0&&c>0&&r<h-1&&c<w-1&&!(std::abs(r-20)<=1&&std::abs(c-20)<=1);
            int i=r*w+c;if(bool(valid[i])!=expected)return 31;
            if(expected&&(std::abs(east[i]-.3f)>1e-6f||std::abs(south[i]+.1f)>1e-6f))return 32;
        }
    }
    if(gf_cuda_terrain_gradient(0,dem.data(),mask.data(),w,h,10.,20.,0,1,
                                east.data(),south.data(),valid.data())!=-2)return 33;
    gf_cuda_runtime_destroy(gpu);
    return 0;
}
