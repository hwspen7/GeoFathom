"""Exact, bounded-frontier graph kernels for projected terrain grids.

An indexed heap stores each unsettled vertex at most once. Distance and
predecessor arrays can be disk-backed; no tile-local path approximation is
used. Work is split into batches so Python can enforce cancellation.
"""
import math
import tempfile
from pathlib import Path
import shutil
from contextlib import ExitStack

import numpy as np
from numba import njit

from imagery.raster import RasterError
from .cancellation import checkpoint


@njit(cache=True,nogil=True)
def _less(a,b,dist):
    return dist[a]<dist[b] or (dist[a]==dist[b] and a<b)


@njit(cache=True,nogil=True)
def _up(heap,pos,dist,i):
    while i>0:
        parent=(i-1)//2
        if not _less(heap[i],heap[parent],dist):
            break
        a,b=heap[i],heap[parent]
        heap[i],heap[parent]=b,a
        pos[a],pos[b]=parent,i
        i=parent


@njit(cache=True,nogil=True)
def _pop(heap,pos,dist,size):
    node=heap[0]
    size-=1
    pos[node]=-2
    if size:
        last=heap[size]
        heap[0]=last
        pos[last]=0
        i=0
        while 2*i+1<size:
            j=2*i+1
            if j+1<size and _less(heap[j+1],heap[j],dist):
                j+=1
            if not _less(heap[j],heap[i],dist):
                break
            a,b=heap[i],heap[j]
            heap[i],heap[j]=b,a
            pos[a],pos[b]=j,i
            i=j
    return node,size


@njit(cache=True,nogil=True)
def _search(z,valid,dist,prev,heap,pos,size,end,dx,dy,max_grade,model,neighbors):
    h,w=z.shape
    for _ in range(4096):
        if size==0:
            return size,True
        node,size=_pop(heap,pos,dist,size)
        if node==end:
            return size,True
        r,c=node//w,node%w
        for k in range(8):
            dr,dc=neighbors[k,0],neighbors[k,1]
            rr,cc=r+dr,c+dc
            if not (0<=rr<h and 0<=cc<w and valid[rr,cc]):
                continue
            if dr and dc and not (valid[r,cc] and valid[rr,c]):
                continue
            target=rr*w+cc
            if pos[target]==-2:
                continue
            horizontal=math.hypot(dr*dy,dc*dx)
            rise=float(z[rr,cc]-z[r,c])
            if math.degrees(math.atan(abs(rise)/horizontal))>max_grade:
                continue
            step=horizontal if model==0 else math.hypot(horizontal,rise)*(1+(4 if model==2 else 1)*(rise/horizontal)**2)
            candidate=dist[node]+step
            if candidate<dist[target]:
                dist[target]=candidate
                prev[target]=node
                i=pos[target]
                if i==-1:
                    i=size
                    size+=1
                    heap[i]=target
                    pos[target]=i
                _up(heap,pos,dist,i)
    return size,False


def exact_route(z,valid,start,end,dx,dy,max_grade,route_model,neighbors,cancel=None,scratch=None):
    """Return the same shortest-path cost as Dijkstra, with O(n) frontier state."""
    if z.ndim!=2 or z.shape!=valid.shape or not all(math.isfinite(x) and x>0 for x in (dx,dy)):
        raise RasterError("Route requires an aligned projected grid and positive spacing.")
    h,w=z.shape
    if any(not (0<=r<h and 0<=c<w and valid[r,c]) for r,c in (start,end)):
        raise RasterError("Route endpoints must be valid grid cells.")
    checkpoint(cancel)
    n=h*w
    first=start[0]*w+start[1];last=end[0]*w+end[1]
    with ExitStack() as stack:
        directory=None
        if scratch is not None:
            scratch=Path(scratch)
            scratch.mkdir(parents=True,exist_ok=True)
            if shutil.disk_usage(scratch).free < 20*n+64*1024**2:
                raise RasterError("Insufficient scratch space for disk-backed route state.")
            directory=Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="route-",dir=scratch)))
        def allocate(name,dtype,fill):
            if directory is None:
                return np.full(n,fill,dtype=dtype)
            array=np.memmap(directory/name,mode="w+",dtype=dtype,shape=(n,))
            # Windows cannot remove mapped files until their handles close.
            stack.callback(array._mmap.close)
            array[:]=fill
            return array
        dist=allocate("distance",np.float64,np.inf)
        prev=allocate("predecessor",np.int32,-1)
        heap=allocate("frontier",np.int32,0)
        pos=allocate("positions",np.int32,-1)
        dist[first]=0;heap[0]=first;pos[first]=0
        size=1;done=False
        offsets=np.asarray([(dr,dc) for dr,dc,*_ in neighbors],dtype=np.int64)
        model={"distance":0,"surface":1,"gentle":2}[route_model]
        while not done:
            checkpoint(cancel)
            size,done=_search(z,valid,dist,prev,heap,pos,size,last,dx,dy,max_grade,model,offsets)
        checkpoint(cancel)
        if not np.isfinite(dist[last]):
            raise RasterError("No valid terrain route within the slope limit.")
        path=[end];node=last
        while node!=first:
            if len(path)%4096==0:checkpoint(cancel)
            node=int(prev[node])
            if node<0 or len(path)>n:raise RasterError("Invalid route predecessor chain.")
            path.append(divmod(node,w))
        path.reverse()
        return path,float(dist[last])


@njit(cache=True,nogil=True)
def accumulate_d8_chunk(accum,receivers,nodes):
    for index in nodes:
        target=receivers[index]
        if target>=0:accum[target]+=accum[index]


@njit(cache=True,nogil=True)
def accumulate_mfd_chunk(z,valid,accum,nodes,dx,dy,exponent,neighbors):
    h,w=z.shape
    receivers=np.empty(8,np.int64)
    slopes=np.empty(8,np.float64)
    for index in nodes:
        r,c=index//w,index%w
        count=0;largest=0.
        for k in range(8):
            dr,dc=neighbors[k,0],neighbors[k,1]
            rr,cc=r+dr,c+dc
            if not (0<=rr<h and 0<=cc<w and valid[rr,cc]):
                continue
            if dr and dc and not (valid[r,cc] and valid[rr,c]):
                continue
            slope=(z[r,c]-z[rr,cc])/math.hypot(dr*dy,dc*dx)
            if slope>0:
                receivers[count]=rr*w+cc
                slopes[count]=slope
                largest=max(largest,slope)
                count+=1
        if count:
            total=0.
            for k in range(count):
                slopes[k]=(slopes[k]/largest)**exponent
                total+=slopes[k]
            amount=accum[index]/total
            for k in range(count):
                accum[receivers[k]]+=amount*slopes[k]
