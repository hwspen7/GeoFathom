#include "geometry.h"
#include <atomic>
#include <cstdint>
#include <cstring>
#include <thread>
#include <vector>
int main(){
    if(gf_buffer_pool_create(0)||gf_buffer_pool_create(63)||
       gf_buffer_pool_create(512ULL*1024*1024+1))return 20;
    std::uint64_t invalid_id=0; void* invalid_ptr=nullptr;
    std::size_t invalid_stats[3]{};
    if(gf_buffer_pool_acquire(nullptr,64,&invalid_id,&invalid_ptr)!=-1||
       gf_buffer_pool_release(nullptr,1)!=-1||
       gf_buffer_pool_stats(nullptr,invalid_stats)!=-1||
       gf_buffer_pool_destroy(nullptr)!=-1)return 21;
    auto* p=gf_buffer_pool_create(4096);
    if(!p)return 1;
    std::uint64_t a=0,b=0,c=0;void *x=nullptr,*y=nullptr,*z=nullptr;
    if(gf_buffer_pool_acquire(p,1024,&a,&x)!=0||
       gf_buffer_pool_acquire(p,3072,&b,&y)!=0||a==b||
       reinterpret_cast<std::uintptr_t>(x)%64!=0)return 2;
    if(gf_buffer_pool_acquire(p,64,&c,&z)!=-1||
       gf_buffer_pool_destroy(p)!=-1)return 3;
    if(gf_buffer_pool_acquire(p,0,&c,&z)!=-1||
       gf_buffer_pool_acquire(p,64,nullptr,&z)!=-1||
       gf_buffer_pool_acquire(p,64,&c,nullptr)!=-1||
       gf_buffer_pool_acquire(p,8192,&c,&z)!=-1||
       gf_buffer_pool_release(p,0)!=-1||gf_buffer_pool_stats(p,nullptr)!=-1)return 22;
    std::memset(x,255,1024);
    if(gf_buffer_pool_release(p,a)!=0||gf_buffer_pool_release(p,a)!=-1)return 4;
    if(gf_buffer_pool_acquire(p,1024,&c,&z)!=0||z!=x||a==c)return 5;
    for(int i=0;i<1024;++i)if(static_cast<unsigned char*>(z)[i]!=0)return 6;
    if(gf_buffer_pool_release(p,b)||gf_buffer_pool_release(p,c))return 7;
    // A larger request must evict unused smaller blocks and preserve the budget.
    if(gf_buffer_pool_acquire(p,4096,&c,&z)!=0)return 23;
    std::size_t eviction[3]{};
    if(gf_buffer_pool_stats(p,eviction)||eviction[0]!=4096||eviction[1]!=4096)return 24;
    if(gf_buffer_pool_release(p,c))return 25;
    std::atomic<int> failures{0};
    std::vector<std::thread> threads;
    for(int t=0;t<8;++t)threads.emplace_back([&]{
        for(int i=0;i<300;++i){
            std::uint64_t id;void* memory;
            if(gf_buffer_pool_acquire(p,128,&id,&memory)==0){
                std::memset(memory,1,128);
                if(gf_buffer_pool_release(p,id))++failures;
            }
        }
    });
    for(auto& t:threads)t.join();
    std::size_t stats[3]{};
    if(failures||gf_buffer_pool_stats(p,stats)||stats[0]>4096||stats[1])return 8;
    return gf_buffer_pool_destroy(p)!=0;
}
