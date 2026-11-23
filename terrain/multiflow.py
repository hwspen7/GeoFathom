"""Bounded hydrology beyond D8: fractional MFD flow and Strahler channel order.

MFD uses Freeman-style power-weighted strictly downhill slopes; all valid
source cells contribute one cell equivalent. Flat and sink cells are outlets
unless an explicit DEM conditioning pass was requested. NoData and diagonal
corner gaps never become fabricated channels.
"""
from collections import deque
from math import hypot, isfinite
import numpy as np
from imagery.raster import RasterError
from .cancellation import checkpoint

_NEIGHBORS=((-1,0),(-1,1),(0,1),(1,1),(1,0),(1,-1),(0,-1),(-1,-1))


def mfd_accumulation(z,valid,dx,dy,exponent=1.1,cancel=None):
    """Return fractional contributing cell equivalents under MFD routing."""
    z=np.asarray(z,dtype=np.float64)
    valid=np.asarray(valid,dtype=bool)
    if z.ndim!=2 or valid.shape!=z.shape or not valid.any():
        raise RasterError("MFD requires an aligned nonempty 2-D elevation mask.")
    if not (isfinite(dx) and isfinite(dy) and dx>0 and dy>0
            and isfinite(exponent) and .5<=exponent<=8):
        raise RasterError("Invalid MFD cell spacing or routing exponent.")
    if not np.isfinite(z[valid]).all():
        raise RasterError("MFD valid elevations must be finite.")
    if valid.size>1_000_000:
        raise RasterError("MFD grid exceeds the bounded one-million-cell budget.")
    checkpoint(cancel)
    h,w=z.shape
    flat_valid=valid.ravel()
    elevations=z.ravel()
    cells=np.flatnonzero(flat_valid)
    # Strict downhill receivers form a DAG even with equal-height plateaus.
    order=cells[np.argsort(elevations[cells],kind="stable")[::-1]]
    accumulation=flat_valid.astype(np.float64)
    for iteration,index in enumerate(order):
        if iteration%2048==0:
            checkpoint(cancel)
        r,c=divmod(int(index),w)
        receivers=[];slopes=[]
        elevation=float(elevations[index])
        for dr,dc in _NEIGHBORS:
            rr,cc=r+dr,c+dc
            if not (0<=rr<h and 0<=cc<w and valid[rr,cc]):
                continue
            # Do not route diagonally through a NoData corner.
            if dr and dc and not (valid[r,cc] and valid[rr,c]):
                continue
            slope=(elevation-float(z[rr,cc]))/hypot(dr*dy,dc*dx)
            if slope>0:
                receivers.append(rr*w+cc)
                slopes.append(slope)
        if not slopes:
            continue
        # Normalize before exponentiation; avoids overflowing on extreme
        # but finite DEM values without changing the physical proportions.
        largest=max(slopes)
        weights=[(s/largest)**exponent for s in slopes]
        total=sum(weights)
        amount=float(accumulation[index])/total
        for receiver,weight in zip(receivers,weights):
            accumulation[receiver]+=amount*weight
    return np.where(valid,accumulation.reshape(z.shape),np.nan)


def strahler_orders(receivers,channel,cancel=None):
    """Classify a thresholded D8 channel DAG using Strahler confluence order.

    Each channel headwater starts at 1. Equal highest upstream orders merge
    to one higher order; a lower-order tributary does not increment it.
    """
    receivers=np.asarray(receivers)
    channel=np.asarray(channel,dtype=bool)
    if receivers.ndim!=2 or receivers.shape!=channel.shape:
        raise RasterError("Stream order requires an aligned D8 receiver grid.")
    nodes=np.flatnonzero(channel.ravel())
    if not nodes.size:
        raise RasterError("No channel cells meet the stream threshold.")
    flat=receivers.ravel()
    mask=channel.ravel()
    n=mask.size
    incoming=np.zeros(n,dtype=np.int32)
    highest=np.zeros(n,dtype=np.int16)
    equal_highest=np.zeros(n,dtype=np.int16)
    order=np.zeros(n,dtype=np.int16)
    for iteration,i in enumerate(nodes):
        if iteration%4096==0:
            checkpoint(cancel)
        destination=int(flat[i])
        if destination<-1 or destination>=n:
            raise RasterError("Invalid D8 receiver index in channel network.")
        if destination>=0 and mask[destination]:
            incoming[destination]+=1
    queue=deque(int(i) for i in nodes if incoming[i]==0)
    visited=0
    while queue:
        if visited%2048==0:
            checkpoint(cancel)
        index=queue.popleft()
        visited+=1
        order[index]=highest[index]+(1 if equal_highest[index]>=2 else 0) if highest[index] else 1
        destination=int(flat[index])
        if destination>=0 and mask[destination]:
            if order[index]>highest[destination]:
                highest[destination]=order[index]
                equal_highest[destination]=1
            elif order[index]==highest[destination]:
                equal_highest[destination]+=1
            incoming[destination]-=1
            if incoming[destination]==0:
                queue.append(destination)
    if visited!=len(nodes):
        raise RasterError("Stream network contains a cycle; cannot assign Strahler order.")
    result=np.full(channel.shape,np.nan,dtype=np.float64)
    result.ravel()[nodes]=order[nodes]
    return result


def shreve_magnitudes(receivers,channel,cancel=None):
    """Additive Shreve stream magnitude on a validated acyclic D8 network."""
    receivers=np.asarray(receivers);channel=np.asarray(channel,dtype=bool)
    if receivers.ndim!=2 or receivers.shape!=channel.shape:
        raise RasterError("Shreve magnitude requires an aligned receiver grid.")
    nodes=np.flatnonzero(channel.ravel())
    if not nodes.size:raise RasterError("No channel cells meet the stream threshold.")
    flat=receivers.ravel();mask=channel.ravel();size=mask.size
    incoming=np.zeros(size,dtype=np.int32)
    values=np.zeros(size,dtype=np.int64)
    for count,index in enumerate(nodes):
        if count%4096==0:checkpoint(cancel)
        dest=int(flat[index])
        if dest<-1 or dest>=size:
            raise RasterError("Invalid D8 receiver index in channel network.")
        if dest>=0 and mask[dest]:incoming[dest]+=1
    queue=deque(int(i) for i in nodes if incoming[i]==0)
    for index in queue:values[index]=1
    visited=0
    while queue:
        if visited%2048==0:checkpoint(cancel)
        index=queue.popleft();visited+=1
        dest=int(flat[index])
        if dest>=0 and mask[dest]:
            values[dest]+=values[index]
            incoming[dest]-=1
            if incoming[dest]==0:queue.append(dest)
    if visited!=len(nodes):
        raise RasterError("Stream network contains a cycle; cannot assign Shreve magnitude.")
    result=np.full(channel.shape,np.nan,dtype=np.float64)
    result.ravel()[nodes]=values[nodes]
    return result
