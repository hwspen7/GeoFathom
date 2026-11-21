#include "geometry.h"
#include <cmath>
#include <vector>
#include <limits>
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
    gf_cuda_runtime_destroy(gpu);
    return 0;
}
