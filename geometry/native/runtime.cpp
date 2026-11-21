#include "geometry.h"
#include <algorithm>
#include <array>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>

namespace {
// Explicit owner: no static native thread pool whose destructor could join
// threads inside a Windows DLL loader lock. Calls are serialized per handle.
class Runtime {
    std::mutex call_lock_, state_lock_;
    std::condition_variable wake_, done_;
    std::vector<std::thread> workers_;
    std::array<int,8> results_{};
    std::function<int(std::size_t,std::size_t)> work_;
    std::size_t count_=0, generation_=0, pending_=0;
    bool stopping_=false;
    void worker(std::size_t id) {
        std::size_t seen=0;
        std::unique_lock<std::mutex> lock(state_lock_);
        while (true) {
            wake_.wait(lock,[&]{return stopping_ || generation_!=seen;});
            if(stopping_) return;
            seen=generation_;
            const auto start=count_*id/workers_.size();
            const auto end=count_*(id+1)/workers_.size();
            lock.unlock();
            int result=0;
            try { if(end>start) result=work_(start,end-start); }
            catch(...) { result=-1; }
            lock.lock();
            results_[id]=result;
            if(--pending_==0) done_.notify_one();
        }
    }
    void shutdown() noexcept {
        { std::lock_guard<std::mutex> lock(state_lock_); stopping_=true; }
        wake_.notify_all();
        for(auto& t:workers_) if(t.joinable()) t.join();
    }
public:
    explicit Runtime(unsigned threads) {
        workers_.reserve(threads);
        try {
            for(unsigned i=0;i<threads;++i)
                workers_.emplace_back([this,i]{worker(i);});
        } catch(...) {shutdown();throw;}
    }
    ~Runtime(){shutdown();}
    int run(std::size_t n,std::function<int(std::size_t,std::size_t)> task) {
        std::lock_guard<std::mutex> caller(call_lock_);
        if(n<65536 || workers_.size()==1) return task(0,n);
        std::unique_lock<std::mutex> lock(state_lock_);
        work_=std::move(task);
        count_=n;
        pending_=workers_.size();
        ++generation_;
        wake_.notify_all();
        done_.wait(lock,[&]{return pending_==0;});
        work_=nullptr;
        int total=0;
        for(std::size_t i=0;i<workers_.size();++i){
            if(results_[i]<0) return -1;
            total+=results_[i];
        }
        return total;
    }
};
constexpr std::size_t max_pixels=16U*1024U*1024U;
}
extern "C" GEOFATHOM_API void* gf_cpu_runtime_create(unsigned threads) noexcept {
    if(threads<1 || threads>8) return nullptr;
    try {return new Runtime(threads);} catch(...) {return nullptr;}
}
extern "C" GEOFATHOM_API void gf_cpu_runtime_destroy(void* runtime) noexcept {
    delete static_cast<Runtime*>(runtime);
}
extern "C" GEOFATHOM_API int gf_cpu_runtime_index(void* runtime,
    const float* a,const float* b,const unsigned char* valid,std::size_t n,
    float* output,unsigned char* mask) noexcept {
    if(!runtime||!a||!b||!valid||!output||!mask||!n||n>max_pixels)return -1;
    try {return static_cast<Runtime*>(runtime)->run(n,[&](auto start,auto len){
        return gf_spectral_normalized_difference(a+start,b+start,valid+start,
            len,output+start,mask+start);
    });} catch(...) {return -1;}
}
extern "C" GEOFATHOM_API int gf_cpu_runtime_change(void* runtime,
    const float* a,const unsigned char* av,const float* b,const unsigned char* bv,
    std::size_t n,float threshold,unsigned char* output) noexcept {
    if(!runtime||!a||!av||!b||!bv||!output||!n||n>max_pixels)return -1;
    try {return static_cast<Runtime*>(runtime)->run(n,[&](auto start,auto len){
        return gf_spectral_change(a+start,av+start,b+start,bv+start,len,
            threshold,output+start);
    });} catch(...) {return -1;}
}
