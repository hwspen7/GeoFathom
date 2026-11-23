"""Nopython D-infinity flux propagation with bounded cancellation checkpoints.

Identical Tarboton triangular-facet geometry and tie ordering to the Python
reference in p1_science.py. All arrays remain C-contiguous NumPy source-grid
matrices; only a fixed 4096-cell traversal chunk enters LLVM JIT code.
"""
import math
import numpy as np
from numba import njit


@njit(cache=True,nogil=True)
def _propagate(z,valid,acc,angles,nodes,facets,directions):
    h,w=z.shape
    for key in nodes:
        r=int(key//w);c=int(key%w);base=z[r,c]
        best_slope=0.0;best_angle=math.nan
        first=-1;second=-1;wf=0.0;ws=0.0
        for j in range(8):
            dr1=int(facets[j,0]);dc1=int(facets[j,1])
            dr2=int(facets[j,2]);dc2=int(facets[j,3])
            r1=r+dr1;c1=c+dc1;r2=r+dr2;c2=c+dc2
            if not(0<=r1<h and 0<=c1<w and 0<=r2<h and 0<=c2<w
                   and valid[r1,c1] and valid[r2,c2]):
                continue
            if (dr1!=0 and dc1!=0 and not(valid[r,c1] and valid[r1,c])) or (
                dr2!=0 and dc2!=0 and not(valid[r,c2] and valid[r2,c])):
                continue
            x1=facets[j,4];y1=facets[j,5]
            x2=facets[j,6];y2=facets[j,7]
            determinant=facets[j,8];a1=facets[j,9];a2=facets[j,10]
            arc=facets[j,11];d1=facets[j,12];d2=facets[j,13]
            delta1=z[r1,c1]-base;delta2=z[r2,c2]-base
            east=-(delta1*y2-delta2*y1)/determinant
            north=-(x1*delta2-x2*delta1)/determinant
            angle=math.atan2(north,east)%(2*math.pi)
            position=(angle-a1)%(2*math.pi)
            if position<=arc+1e-12:
                fraction=min(1.0,max(0.0,position/arc))
                t1=1-fraction if delta1<0 else 0.0
                t2=fraction if delta2<0 else 0.0
                total=t1+t2
                if total>0:
                    slope=math.hypot(east,north)
                    if slope>best_slope:
                        best_slope=slope;best_angle=angle
                        first=-1;second=-1;wf=0.0;ws=0.0
                        if t1>0:
                            first=r1*w+c1;wf=t1/total
                        if t2>0:
                            if first<0:
                                first=r2*w+c2;wf=t2/total
                            else:
                                second=r2*w+c2;ws=t2/total
            else:
                slope=max(0.0,-delta1/d1)
                if slope>best_slope:
                    best_slope=slope;best_angle=a1
                    first=r1*w+c1;second=-1;wf=1.0;ws=0.0
                slope=max(0.0,-delta2/d2)
                if slope>best_slope:
                    best_slope=slope;best_angle=a2
                    first=r2*w+c2;second=-1;wf=1.0;ws=0.0
        if first<0:
            # A partially masked triangle can leave one legitimate cardinal
            # drainage receiver; diagonals still cannot cut NoData corners.
            dx=abs(facets[0,4]);dy=abs(facets[2,5])
            for j in range(8):
                dr=int(directions[j,0]);dc=int(directions[j,1])
                rr=r+dr;cc=c+dc
                if not(0<=rr<h and 0<=cc<w and valid[rr,cc]):continue
                if dr!=0 and dc!=0 and not(valid[r,cc] and valid[rr,c]):continue
                distance=math.hypot(dc*dx,dr*dy)
                slope=(base-z[rr,cc])/distance
                if slope>best_slope:
                    best_slope=slope
                    best_angle=math.atan2(-dr*dy,dc*dx)%(2*math.pi)
                    first=rr*w+cc;second=-1;wf=1.0;ws=0.0
        if first>=0:
            angles[r,c]=best_angle
            value=acc[r,c]
            rr=first//w;cc=first%w
            acc[rr,cc]+=value*wf
            if second>=0:
                rr=second//w;cc=second%w
                acc[rr,cc]+=value*ws


def accelerate_dinfinity(z,valid,acc,angles,nodes,facets,directions,checkpoint,cancel=None):
    """Preserve cancellation responsiveness even for million-cell jobs."""
    facets=np.ascontiguousarray(facets,dtype=np.float64)
    directions=np.ascontiguousarray(directions,dtype=np.int64)
    for i in range(0,len(nodes),4096):
        checkpoint(cancel)
        _propagate(z,valid,acc,angles,nodes[i:i+4096],facets,directions)
    checkpoint(cancel)
