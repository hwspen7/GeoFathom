#include "geometry.h"
#include <cstdlib>
#include <cstdint>
#include <random>
#include <vector>
int main(){
    std::mt19937 gen(4383);
    const unsigned supported=gf_mask_transition_backends();
    if(!(supported&1))return 1;
    // Unaligned rows, every short vector tail, and 1-, 2-, 4-byte classes.
    for(std::size_t w=1;w<=129;++w){
        for(std::size_t h:{1U,2U,17U}){
            std::vector<unsigned char> data(w*h+1);
            for(auto& v:data)v=static_cast<unsigned char>(gen()%5);
            const auto* p=data.data()+1;
            int expected=0;
            for(std::size_t y=0;y<h;++y)
                for(std::size_t x=0;x<w;++x){
                    auto i=y*w+x;
                    if(x)expected+=p[i]!=p[i-1];
                    if(y)expected+=p[i]!=p[i-w];
                }
            for(unsigned b=0;b<=4;++b){
                int value=gf_mask_transitions_backend(p,w,h,b);
                if(b==0||(supported&(1U<<(b-1)))){
                    if(value!=expected)return 2;
                }else if(value!=-1)return 3;
            }
        }
    }
    if(gf_mask_transitions_backend(nullptr,10,10,0)!=-1)return 4;
    if(gf_mask_transitions_backend(reinterpret_cast<const unsigned char*>("x"),1,1,99)!=-1)return 5;
#ifdef __aarch64__
    if(!(supported&8))return 6;
#endif
    return 0;
}
