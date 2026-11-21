"""Deterministic equal-interval, quantile and Fisher-Jenks map classification.

Classification uses finite numeric source values, not untrusted expressions.
Jenks is computed on a capped, evenly sampled sorted population to keep
interactive maps responsive with large tables.
"""
import math
from collections.abc import Sequence

import numpy as np
from storage.database import StorageError


def classify(values:Sequence[float],classes:int=5,method:str="quantile")->dict:
    if method not in {"equal_interval","quantile","jenks"}:
        raise StorageError("Classification method must be equal_interval, quantile or jenks.")
    if not 2<=classes<=9:raise StorageError("Classification requires 2–9 classes.")
    if not 2<=len(values)<=10000:raise StorageError("Provide 2–10000 numeric values.")
    try:ary=np.asarray(values,dtype=np.float64)
    except (TypeError,ValueError) as error:
        raise StorageError("Classification values must be finite numbers.") from error
    if not np.isfinite(ary).all():
        raise StorageError("Classification values must be finite numbers.")
    ary=np.sort(ary)
    low=float(ary[0]);high=float(ary[-1])
    if low==high:raise StorageError("All input values are equal. Use one class instead.")
    count=min(classes,len(np.unique(ary)))
    if method=="equal_interval":
        breaks=list(np.linspace(low,high,count+1)[1:-1])
    elif method=="quantile":
        breaks=list(np.quantile(ary,np.linspace(0,1,count+1)[1:-1]))
    else:
        # Fisher-Jenks optimal dynamic programming over a bounded sorted sample.
        # Duplicate inputs and high-cardinality classes are intentionally bounded.
        samples=ary if len(ary)<=500 else ary[
            np.rint(np.linspace(0,len(ary)-1,500)).astype(int)]
        sample=np.asarray(samples,dtype=np.float64)
        n=len(sample)
        prefix=np.r_[0,np.cumsum(sample)]
        square=np.r_[0,np.cumsum(sample*sample)]
        costs=np.full((count+1,n+1),np.inf)
        previous=np.zeros((count+1,n+1),dtype=np.int32)
        costs[0,0]=0
        for k in range(1,count+1):
            for right in range(k,n+1):
                lefts=np.arange(k-1,right)
                length=right-lefts
                total=prefix[right]-prefix[lefts]
                deviation=np.maximum(0,square[right]-square[lefts]-total*total/length)
                options=costs[k-1,lefts]+deviation
                position=int(np.argmin(options))
                costs[k,right]=options[position]
                previous[k,right]=int(lefts[position])
        breaks=[]
        end=n
        for k in range(count,1,-1):
            start=int(previous[k,end])
            breaks.append(float(sample[start]))
            end=start
        breaks.reverse()
    # Drop duplicate thresholds, which would make indistinguishable legend bins.
    unique=[]
    for value in breaks:
        v=float(value)
        if low<v<high and (not unique or v>unique[-1]):
            unique.append(v)
    ranges=[]
    points=[low,*unique,high]
    for idx,(a,b) in enumerate(zip(points,points[1:])):
        ranges.append({"min":a,"max":b,"inclusive_upper":idx==len(points)-2})
    return {"method":method,"min":low,"max":high,"breaks":unique,
            "classes":len(ranges),"ranges":ranges,"samples":len(ary),
            "method_note":"Jenks uses an evenly sampled <=500-value population" if method=="jenks" else
            "All input values used"}
