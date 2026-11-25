#include "geometry.h"
#include <vector>
#include <thread>
#include <limits>
#include <cstdlib>
int main() {
    constexpr std::size_t n=262147;
    std::vector<float> a(n,200),b(n,50),reference(n),out(n);
    std::vector<unsigned char> valid(n,1),expected(n),mask(n),change(n);
    a[0]=std::numeric_limits<float>::quiet_NaN();
    valid[n-1]=0;
    const int count=gf_spectral_normalized_difference(a.data(),b.data(),
        valid.data(),n,reference.data(),expected.data());
    if(count!=static_cast<int>(n-2) || gf_cpu_runtime_create(0))return 1;
    void* pool=gf_cpu_runtime_create(4);
    if(!pool)return 2;
    for(int i=0;i<8;++i){
        if(gf_cpu_runtime_index(pool,a.data(),b.data(),valid.data(),n,
            out.data(),mask.data())!=count || out!=reference || mask!=expected)
            return 3;
    }
    int rc1=-1,rc2=-1;
    std::vector<float> second(n);std::vector<unsigned char> secondmask(n);
    std::thread first([&]{rc1=gf_cpu_runtime_index(pool,a.data(),b.data(),
        valid.data(),n,out.data(),mask.data());});
    std::thread other([&]{rc2=gf_cpu_runtime_index(pool,a.data(),b.data(),
        valid.data(),n,second.data(),secondmask.data());});
    first.join();other.join();
    if(rc1!=count || rc2!=count || second!=reference || secondmask!=expected)return 4;
    if(gf_cpu_runtime_change(pool,out.data(),mask.data(),reference.data(),
        expected.data(),n,.1f,change.data())!=0)return 5;
    if(gf_cpu_runtime_index(pool,a.data(),b.data(),valid.data(),0,
        out.data(),mask.data())!=-1)return 6;
    if(gf_cpu_runtime_create(9))return 7;
    if(gf_cpu_runtime_index(nullptr,a.data(),b.data(),valid.data(),n,out.data(),mask.data())!=-1||
       gf_cpu_runtime_index(pool,nullptr,b.data(),valid.data(),n,out.data(),mask.data())!=-1||
       gf_cpu_runtime_index(pool,a.data(),nullptr,valid.data(),n,out.data(),mask.data())!=-1||
       gf_cpu_runtime_index(pool,a.data(),b.data(),nullptr,n,out.data(),mask.data())!=-1||
       gf_cpu_runtime_index(pool,a.data(),b.data(),valid.data(),n,nullptr,mask.data())!=-1||
       gf_cpu_runtime_index(pool,a.data(),b.data(),valid.data(),n,out.data(),nullptr)!=-1||
       gf_cpu_runtime_index(pool,a.data(),b.data(),valid.data(),16777217,out.data(),mask.data())!=-1)return 8;
    if(gf_cpu_runtime_change(pool,nullptr,mask.data(),reference.data(),expected.data(),n,.1f,change.data())!=-1||
       gf_cpu_runtime_change(pool,out.data(),nullptr,reference.data(),expected.data(),n,.1f,change.data())!=-1||
       gf_cpu_runtime_change(pool,out.data(),mask.data(),nullptr,expected.data(),n,.1f,change.data())!=-1||
       gf_cpu_runtime_change(pool,out.data(),mask.data(),reference.data(),nullptr,n,.1f,change.data())!=-1||
       gf_cpu_runtime_change(pool,out.data(),mask.data(),reference.data(),expected.data(),0,.1f,change.data())!=-1||
       gf_cpu_runtime_change(pool,out.data(),mask.data(),reference.data(),expected.data(),n,.1f,nullptr)!=-1||
       gf_cpu_runtime_change(pool,out.data(),mask.data(),reference.data(),expected.data(),n,-.1f,change.data())!=-1)return 9;
    gf_cpu_runtime_destroy(pool);
    // Explicitly cover the scalar scheduling path with one worker and a small tile.
    pool=gf_cpu_runtime_create(1);
    if(!pool)return 10;
    if(gf_cpu_runtime_index(pool,a.data(),b.data(),valid.data(),1,out.data(),mask.data())!=0)return 11;
    if(gf_cpu_runtime_index(pool,a.data(),b.data(),valid.data(),n,out.data(),mask.data())!=count)return 12;
    gf_cpu_runtime_destroy(pool);
    gf_cpu_runtime_destroy(nullptr);
    return 0;
}
