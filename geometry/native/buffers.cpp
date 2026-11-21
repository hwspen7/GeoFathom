#include "geometry.h"
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <limits>
#include <mutex>
#include <new>
#include <vector>

namespace {
constexpr std::size_t alignment=64;
constexpr std::size_t limit=512U*1024U*1024U;
struct Block {
    void* bytes;
    std::size_t capacity;
    std::uint64_t lease;
};
struct Pool {
    explicit Pool(std::size_t n):budget(n){}
    ~Pool(){for(auto& b:blocks)::operator delete(b.bytes,std::align_val_t(alignment));}
    std::mutex mutex;
    std::vector<Block> blocks;
    const std::size_t budget;
    std::size_t reserved=0;
    std::uint64_t next=1;
};
}
extern "C" GEOFATHOM_API void* gf_buffer_pool_create(std::size_t budget) noexcept {
    if(budget<alignment||budget>limit)return nullptr;
    try{return new Pool(budget);}catch(...){return nullptr;}
}
extern "C" GEOFATHOM_API int gf_buffer_pool_acquire(void* handle,std::size_t bytes,
    std::uint64_t* lease,void** data) noexcept {
    if(!handle||!lease||!data||bytes==0||bytes>limit)return -1;
    *lease=0;*data=nullptr;
    auto& p=*static_cast<Pool*>(handle);
    try{
        std::lock_guard<std::mutex> guard(p.mutex);
        const auto rounded=((bytes+alignment-1)/alignment)*alignment;
        if(rounded>p.budget||p.next==std::numeric_limits<std::uint64_t>::max())return -1;
        auto best=p.blocks.end();
        for(auto i=p.blocks.begin();i!=p.blocks.end();++i)
            if(i->lease==0&&i->capacity>=rounded&&(best==p.blocks.end()||i->capacity<best->capacity))
                best=i;
        if(best==p.blocks.end()){
            // Evict only unleased blocks, never pointers used by other callers.
            for(auto i=p.blocks.begin();i!=p.blocks.end()&&rounded>p.budget-p.reserved;){
                if(i->lease==0){
                    p.reserved-=i->capacity;
                    ::operator delete(i->bytes,std::align_val_t(alignment));
                    i=p.blocks.erase(i);
                }else ++i;
            }
            if(rounded>p.budget-p.reserved)return -1;
            auto* memory=::operator new(rounded,std::align_val_t(alignment),std::nothrow);
            if(!memory)return -1;
            try{p.blocks.push_back({memory,rounded,0});}
            catch(...){::operator delete(memory,std::align_val_t(alignment));return -1;}
            p.reserved+=rounded;
            best=p.blocks.end()-1;
        }
        // Old data must not leak into a later tensor or task.
        std::memset(best->bytes,0,bytes);
        best->lease=p.next++;
        *lease=best->lease;*data=best->bytes;
        return 0;
    }catch(...){return -1;}
}
extern "C" GEOFATHOM_API int gf_buffer_pool_release(void* handle,std::uint64_t id) noexcept {
    if(!handle||id==0)return -1;
    auto& p=*static_cast<Pool*>(handle);
    try{
        std::lock_guard<std::mutex> guard(p.mutex);
        for(auto& b:p.blocks)if(b.lease==id){b.lease=0;return 0;}
    }catch(...){}
    return -1;
}
extern "C" GEOFATHOM_API int gf_buffer_pool_stats(void* handle,std::size_t* out) noexcept {
    if(!handle||!out)return -1;
    auto& p=*static_cast<Pool*>(handle);
    try{
        std::lock_guard<std::mutex> guard(p.mutex);
        out[0]=p.reserved;out[1]=0;out[2]=p.budget;
        for(const auto& b:p.blocks)if(b.lease)out[1]+=b.capacity;
        return 0;
    }catch(...){return -1;}
}
extern "C" GEOFATHOM_API int gf_buffer_pool_destroy(void* handle) noexcept {
    if(!handle)return -1;
    auto* p=static_cast<Pool*>(handle);
    // ABI caller must prevent new calls during destruction.
    try{
        {std::lock_guard<std::mutex> guard(p->mutex);
         for(const auto& b:p->blocks)if(b.lease)return -1;}
        delete p;return 0;
    }catch(...){return -1;}
}
